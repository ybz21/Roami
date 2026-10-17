// transfer.go：M1 真实文件传输——分块发送 + 背压 + 取消 + 共享校验。
//
// 通路照 p2p-direct-transfer-tech.md §2.2/§3.4：
//   - 控制帧 = text message（JSON）：meta / eof / error。
//   - 数据帧 = binary message（一条 message 一帧）：[seq:u32 LE][payload ≤ 16 KiB]。
//   - 背压照抄 pion data-channels-flow-control 示例：SetBufferedAmountLowThreshold + OnBufferedAmountLow。
//   - 取消：ctx 贯穿到 os.Open 读循环；p2p/cancel 或 PC/DC 关闭 → session.finish → cancel()+done=1 → 停读。
//   - 共享校验：调 api.ValidateDownloadPath，与 HTTP 下载逐字节一致（评审点4）。
//
// spike 自测支路：op=="spike" 仍发 8 MiB 随机数据 + eof（window.roamP2PSpike 传输自测继续可用），
// 绝不读 /dev/urandom 之类真文件（会无限流）。op!="spike" 即真实文件路径。
package p2p

import (
	"context"
	"crypto/rand"
	"encoding/binary"
	"encoding/json"
	"io"
	"log"
	"os"
	"sync/atomic"

	"github.com/ybz21/Roami/backend/api"

	"github.com/pion/webrtc/v4"
)

const (
	// chunkBytes 是数据帧 payload 上限（每条 message 一帧，保留消息边界）。
	chunkBytes = 16 * 1024
	// hiWater 是背压高水位：BufferedAmount 超过即暂停发送，等 OnBufferedAmountLow 唤醒。
	hiWater = 8 * 1024 * 1024
)

// metaFrame 是 meta 控制帧结构（§2.2）。
type metaFrame struct {
	T          string `json:"t"`
	TransferID string `json:"transferId"`
	Name       string `json:"name"`
	Size       int64  `json:"size"`
	Mtime      int64  `json:"mtime"`
	Chunk      int    `json:"chunk"`
}

// errFrameText 拼一个 error 控制帧（让前端回退 frp）。msg 走 json 转义防注入。
func errFrameText(msg string) string {
	b, _ := json.Marshal(struct {
		T   string `json:"t"`
		Msg string `json:"msg"`
	}{T: "error", Msg: msg})
	return string(b)
}

// serveFile 在 DataChannel 打开后把真实文件分块发给对端。
//
// 校验与所有控制帧（含 error）都在 dc.OnOpen 内做（M1 修复：pre-check 的 error 帧若在
// DC 尚未 open 时 SendText 会被丢弃，前端收不到 error 无法回退 frp）。故校验早退的
// error{bad-path/stat-error/dir-not-supported/not-regular-file} 一律放到 OnOpen 里发，
// 保证 DC open 后才发帧，前端必然收到。成功路径行为不变。
//
// 发送（OnOpen 内）：先校验 → error 早退或 meta 控制帧，再 16 KiB/条二进制帧 [seq][payload]，
// EOF → eof 控制帧。每轮检查 ctx.Done() 与 t.done（原子），命中即停发；背压超高水位则等唤醒或 ctx.Done。
func serveFile(ctx context.Context, dc *webrtc.DataChannel, t *transfer, rawPath string) {
	// 背压：高水位一半设为低水位阈值，OnBufferedAmountLow 唤醒发送循环。
	dc.SetBufferedAmountLowThreshold(hiWater / 2)
	resume := make(chan struct{}, 1)
	dc.OnBufferedAmountLow(func() {
		select {
		case resume <- struct{}{}:
		default:
		}
	})

	dc.OnOpen(func() {
		// 校验放 OnOpen 内：确保 DC 已 open，error 帧不会被丢弃、前端能回退 frp。
		path, err := api.ValidateDownloadPath(rawPath)
		if err != nil {
			_ = dc.SendText(errFrameText("bad-path"))
			return
		}
		info, err := os.Stat(path)
		if err != nil {
			_ = dc.SendText(errFrameText("stat-error"))
			return
		}
		if info.IsDir() {
			// 目录二期再说，仍走 frp。
			_ = dc.SendText(errFrameText("dir-not-supported"))
			return
		}
		// 只发普通文件：字符设备/管道等（如 /dev/urandom）会无限流，拒之走 frp。
		if !info.Mode().IsRegular() {
			_ = dc.SendText(errFrameText("not-regular-file"))
			return
		}

		f, err := os.Open(path)
		if err != nil {
			_ = dc.SendText(errFrameText("open-error"))
			return
		}
		defer f.Close()

		mb, _ := json.Marshal(metaFrame{
			T:          "meta",
			TransferID: t.id,
			Name:       info.Name(),
			Size:       info.Size(),
			Mtime:      info.ModTime().Unix(),
			Chunk:      chunkBytes,
		})
		if err := dc.SendText(string(mb)); err != nil {
			log.Printf("p2p: transfer=%s send meta: %v", t.id, err)
			return
		}
		log.Printf("p2p: transfer=%s meta name=%q size=%d chunk=%d", t.id, info.Name(), info.Size(), chunkBytes)

		buf := make([]byte, chunkBytes)
		frame := make([]byte, 4+chunkBytes)
		var seq uint32
		var sent int64
		for {
			// 取消/回退：ctx.Done 或 done 置位即停读停发。
			if atomic.LoadInt32(&t.done) == 1 {
				log.Printf("p2p: transfer=%s done set, stop reading at %d bytes", t.id, sent)
				return
			}
			select {
			case <-ctx.Done():
				log.Printf("p2p: transfer=%s ctx canceled, stop reading at %d bytes", t.id, sent)
				return
			default:
			}

			n, readErr := f.Read(buf)
			if n > 0 {
				binary.LittleEndian.PutUint32(frame, seq)
				copy(frame[4:], buf[:n])
				if err := dc.Send(frame[:4+n]); err != nil {
					log.Printf("p2p: transfer=%s dc.Send: %v", t.id, err)
					return
				}
				seq++
				sent += int64(n)

				// 背压：缓冲超高水位则等唤醒（或取消）。
				for dc.BufferedAmount() > hiWater {
					select {
					case <-resume:
					case <-ctx.Done():
						log.Printf("p2p: transfer=%s ctx canceled while backpressured at %d bytes", t.id, sent)
						return
					}
				}
			}

			if readErr == io.EOF {
				if err := dc.SendText(`{"t":"eof"}`); err != nil {
					log.Printf("p2p: transfer=%s send eof: %v", t.id, err)
					return
				}
				log.Printf("p2p: transfer=%s sent %d bytes (eof)", t.id, sent)
				return
			}
			if readErr != nil {
				// 源文件读错 → 前端回退 frp。
				_ = dc.SendText(errFrameText("read-error"))
				log.Printf("p2p: transfer=%s read error at %d bytes: %v", t.id, sent, readErr)
				return
			}
		}
	})
}

// serveSpike 是 transport 自测支路：op=="spike" 时发固定大小随机数据 + eof。
// 供 window.roamP2PSpike 的传输自测继续可用；绝不读真文件。
func serveSpike(ctx context.Context, dc *webrtc.DataChannel, t *transfer) {
	dc.SetBufferedAmountLowThreshold(hiWater / 2)
	resume := make(chan struct{}, 1)
	dc.OnBufferedAmountLow(func() {
		select {
		case resume <- struct{}{}:
		default:
		}
	})

	dc.OnOpen(func() {
		buf := make([]byte, spikeChunkBytes)
		var sent int
		for sent < spikeTotalBytes {
			if atomic.LoadInt32(&t.done) == 1 {
				return
			}
			select {
			case <-ctx.Done():
				return
			default:
			}
			if _, err := rand.Read(buf); err != nil {
				_ = dc.SendText(errFrameText("rand"))
				return
			}
			if err := dc.Send(buf); err != nil {
				log.Printf("p2p: transfer=%s dc.Send: %v", t.id, err)
				return
			}
			sent += len(buf)
			for dc.BufferedAmount() > hiWater {
				select {
				case <-resume:
				case <-ctx.Done():
					return
				}
			}
		}
		if err := dc.SendText(`{"t":"eof"}`); err != nil {
			log.Printf("p2p: transfer=%s send eof: %v", t.id, err)
			return
		}
		log.Printf("p2p: transfer=%s spike sent %d bytes (eof)", t.id, sent)
	})
}
