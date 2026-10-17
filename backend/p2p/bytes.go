// bytes.go：浏览器向节点要「某个文件的某一段」——图片、视频、PDF、Office 预览都从这条路拿。
//
// 与 transfer.go 的整份下载是两回事：
//   - transfer.go 是「点下载按钮」，一次一个 PC、一整个文件、落盘。
//   - 这里是**一问一答**：一条 DataChannel 一次 {path,offset,length}，回 meta + 数据帧 + eof。
//     `<video>` 拖一次进度条就是一次新的 Range 请求，所以通道开在**常驻 PC** 上，
//     绝不为每一段重新打洞（打一次洞 0.7s，拖进度条会拖出十几次）。
//
// 谁来调用：前端 Service Worker 拦到 /api/file/raw 就走这里（见 frontend/src/p2p/file-bytes.ts）。
// 任何一步出错都回 error 帧，前端原样去走 HTTP —— 直连只是快路，不是唯一的路。
package p2p

import (
	"encoding/binary"
	"encoding/json"
	"io"
	"log"
	"mime"
	"net/http"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"

	"github.com/ybz21/Roami/backend/api"

	"github.com/pion/webrtc/v4"
)

// bytesReq 是通道上的第一帧（text）：要哪个文件的哪一段。
type bytesReq struct {
	Path   string `json:"path"`
	Offset int64  `json:"offset"`
	Length int64  `json:"length"` // 0 = 从 offset 一直到文件末尾
}

// bytesMeta 是回给前端的第一帧（text）。size 是**整个文件**多大——
// 少了它，Service Worker 拼不出 206 的 Content-Range，浏览器就不让拖进度条。
type bytesMeta struct {
	T           string `json:"t"`
	Name        string `json:"name"`
	Size        int64  `json:"size"`
	Offset      int64  `json:"offset"`
	Length      int64  `json:"length"`
	Mtime       int64  `json:"mtime"`
	ContentType string `json:"contentType"`
	Chunk       int    `json:"chunk"`
}

// serveBytes 处理一条 label 前缀为 "bytes" 的通道：只收一个请求，发完即关。
func serveBytes(dc *webrtc.DataChannel) {
	var once sync.Once
	var closed int32
	dc.OnClose(func() { atomic.StoreInt32(&closed, 1) })
	dc.OnError(func(error) { atomic.StoreInt32(&closed, 1) })
	dc.OnMessage(func(msg webrtc.DataChannelMessage) {
		if !msg.IsString {
			return // 数据帧只往一个方向走；二进制进来了当没看见
		}
		data := append([]byte(nil), msg.Data...)
		// 起 goroutine：OnMessage 在 SCTP 读循环上，堵在这儿会卡住整条 PC 的收包。
		once.Do(func() { go handleBytes(dc, data, &closed) })
	})
}

func handleBytes(dc *webrtc.DataChannel, raw []byte, closed *int32) {
	defer func() { _ = dc.Close() }()

	var req bytesReq
	if err := json.Unmarshal(raw, &req); err != nil {
		_ = dc.SendText(errFrameText("bad-request"))
		return
	}
	// 与 HTTP 下载同一把锁：共享校验逐字节一致，直连不能成为绕过校验的后门。
	path, err := api.ValidateDownloadPath(req.Path)
	if err != nil {
		_ = dc.SendText(errFrameText("bad-path"))
		return
	}
	info, err := os.Stat(path)
	if err != nil {
		_ = dc.SendText(errFrameText("stat-error"))
		return
	}
	if info.IsDir() || !info.Mode().IsRegular() {
		// 目录和字符设备（/dev/urandom 会无限流）一律不发
		_ = dc.SendText(errFrameText("not-regular-file"))
		return
	}
	size := info.Size()
	offset := req.Offset
	if offset < 0 || offset > size {
		_ = dc.SendText(errFrameText("bad-range"))
		return
	}
	length := size - offset
	if req.Length > 0 && req.Length < length {
		length = req.Length
	}

	f, err := os.Open(path)
	if err != nil {
		_ = dc.SendText(errFrameText("open-error"))
		return
	}
	defer f.Close()

	ctype := contentTypeOf(f, path)
	if offset > 0 {
		if _, err := f.Seek(offset, io.SeekStart); err != nil {
			_ = dc.SendText(errFrameText("seek-error"))
			return
		}
	}

	mb, _ := json.Marshal(bytesMeta{
		T: "meta", Name: info.Name(), Size: size, Offset: offset, Length: length,
		Mtime: info.ModTime().Unix(), ContentType: ctype, Chunk: chunkBytes,
	})
	if err := dc.SendText(string(mb)); err != nil {
		return
	}

	// 背压：和 transfer.go 同款（高水位停、OnBufferedAmountLow 唤醒）。
	dc.SetBufferedAmountLowThreshold(hiWater / 2)
	resume := make(chan struct{}, 1)
	dc.OnBufferedAmountLow(func() {
		select {
		case resume <- struct{}{}:
		default:
		}
	})

	buf := make([]byte, chunkBytes)
	frame := make([]byte, 4+chunkBytes)
	var seq uint32
	var sent int64
	for sent < length {
		if atomic.LoadInt32(closed) == 1 {
			// 浏览器取消了（拖进度条、关页面）：别再往一条没人听的通道里灌
			log.Printf("p2p: bytes %s canceled at %d/%d", info.Name(), sent, length)
			return
		}
		want := int64(chunkBytes)
		if r := length - sent; r < want {
			want = r
		}
		n, readErr := f.Read(buf[:want])
		if n > 0 {
			binary.LittleEndian.PutUint32(frame, seq)
			copy(frame[4:], buf[:n])
			if err := dc.Send(frame[:4+n]); err != nil {
				return
			}
			seq++
			sent += int64(n)
			for dc.BufferedAmount() > hiWater {
				if atomic.LoadInt32(closed) == 1 {
					return
				}
				<-resume
			}
		}
		if readErr != nil {
			if readErr != io.EOF {
				_ = dc.SendText(errFrameText("read-error"))
				return
			}
			break
		}
	}
	if sent != length {
		// 读到的比说好的少（文件被截断/换掉）：明确报错，别让前端拼出一个短文件当成功
		_ = dc.SendText(errFrameText("short-read"))
		return
	}
	_ = dc.SendText(`{"t":"eof"}`)
	log.Printf("p2p: bytes %s offset=%d sent=%d type=%s", info.Name(), offset, sent, ctype)
}

// contentTypeOf 先按扩展名判，判不出再嗅前 512 字节（与 http.ServeFile 的顺序一致，
// 免得同一个文件在 HTTP 和直连两条路上拿到两种 Content-Type）。
func contentTypeOf(f *os.File, path string) string {
	if t := mime.TypeByExtension(filepath.Ext(path)); t != "" {
		return t
	}
	var head [512]byte
	n, _ := f.Read(head[:])
	if _, err := f.Seek(0, io.SeekStart); err != nil {
		return "application/octet-stream"
	}
	if n == 0 {
		return "application/octet-stream"
	}
	return http.DetectContentType(head[:n])
}
