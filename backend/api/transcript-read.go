package api

// transcript-read.go：按**字节偏移**读转录。
//
// 为什么要有这一层：原来读一次转录 ≈ 分配一遍整个文件。
//
//   · 首屏走 tailLines：从头 Scan 到尾，每行一次 sc.Text()（一次字符串分配），
//     只为了留下最后几百行；
//   · 增量轮询的 offset 是**行号**，所以每次都得从第 1 行重新数一遍。
//
// 本机实测（299MB 的 JSONL）：一次请求 6.1 秒、RSS +59MB；四个并发把 RSS 从
// 214MB 顶到 419MB。对话页每隔几秒轮询一次，几个客户端一开，后端 RSS 就能堆到
// 4GB 以上——不是泄露（静置几十秒 GC 全还回去，活堆始终 ~215MB），是**每次轮询
// 都在分配一整个文件**。
//
// 改法两条，都是把 O(文件) 变成 O(要的那点)：
//
//   ① 首屏从**文件尾往回读**，只碰最后那几百行所在的那几个块；
//   ② 增量 offset 改成**字节偏移**，Seek 过去只读新增的部分。
//
// 行号也随之退场：ID 兜底改用**行首字节偏移**——它同样唯一且稳定，而且首屏与增量
// 两条路算出来的是同一个值（行号做不到：首屏那条路根本不知道自己是第几行）。

import (
	"bytes"
	"errors"
	"io"
	"os"
)

// 往回找尾部时每次读这么多。1 MiB 覆盖绝大多数「最后几百行」，
// 不够就再往前读一块，而不是一次把整个文件吸进来。
const tailChunkSize = 1 << 20

// transcriptLine 是一行原文加上它的行首字节偏移。
// 偏移既当 ID 兜底，也当下一次轮询的续读位置。
type transcriptLine struct {
	At   int64 // 行首在文件中的字节偏移
	Text []byte
}

// readTail 从文件尾往回取最后 keep 行。
//
// 返回的 more 表示「前面还有」——前端据此显示「加载更早」。
// keep<=0 视为不限；对外首屏接口始终提供分页上限。
func readTail(f *os.File, keep int) (lines []transcriptLine, size int64, more bool, err error) {
	return readTailBefore(f, keep, 0)
}

// before is an exclusive byte cursor; zero starts with the newest records.
func readTailBefore(f *os.File, keep int, before int64) (lines []transcriptLine, size int64, more bool, err error) {
	size, err = f.Seek(0, io.SeekEnd)
	if err != nil {
		return nil, 0, false, err
	}
	if before > 0 && before < size {
		size = before
	}
	if size == 0 {
		return nil, 0, false, nil
	}
	if keep <= 0 {
		lines, err = readFrom(f, 0, size)
		return lines, size, false, err
	}

	// 从尾往前扩，直到攒够 keep+1 个换行（多要一个是为了确定第一行的起点）
	var start int64 = size
	var buf []byte
	for start > 0 {
		chunk := int64(tailChunkSize)
		if start < chunk {
			chunk = start
		}
		start -= chunk
		head := make([]byte, chunk)
		if _, err = f.ReadAt(head, start); err != nil && !errors.Is(err, io.EOF) {
			return nil, 0, false, err
		}
		buf = append(head, buf...)
		if bytes.Count(buf, []byte{'\n'}) > keep {
			break
		}
	}

	// buf 覆盖 [start, size)。切成行，只留最后 keep 行。
	lines = splitLines(buf, start)
	if len(lines) > keep {
		lines = lines[len(lines)-keep:]
		more = true
	} else if start > 0 {
		more = true // 块边界正好切在这儿：前面确实还有
	}
	return lines, size, more, nil
}

// readFrom 从 off 读到 end。
//
// off 落在**半行中间**时跳到下一个换行——这样任何 offset 都不会切出半条 JSON
// （旧前端传来的行号偏移也炸不了）。判据是看 off 前一个字节是不是换行：正常续读
// 时 off 正好是行首，那一跳会把这一行整个吃掉，而它恰恰是本轮唯一的新内容。
func readFrom(f *os.File, off, end int64) ([]transcriptLine, error) {
	if off >= end {
		return nil, nil
	}
	if _, err := f.Seek(off, io.SeekStart); err != nil {
		return nil, err
	}
	buf := make([]byte, end-off)
	n, err := io.ReadFull(f, buf)
	if err != nil && !errors.Is(err, io.ErrUnexpectedEOF) && !errors.Is(err, io.EOF) {
		return nil, err
	}
	buf = buf[:n]
	if off > 0 && !atLineStart(f, off) {
		if i := bytes.IndexByte(buf, '\n'); i >= 0 {
			off += int64(i) + 1
			buf = buf[i+1:]
		} else {
			return nil, nil // 这一段里连个换行都没有：还没写完整一行
		}
	}
	return splitLines(buf, off), nil
}

// atLineStart 看 off 前一个字节是不是换行。off==0 时天然是行首。
func atLineStart(f *os.File, off int64) bool {
	if off <= 0 {
		return true
	}
	var b [1]byte
	if _, err := f.ReadAt(b[:], off-1); err != nil {
		return false // 读不到就当半行处理：宁可少一行，也不要半条 JSON
	}
	return b[0] == '\n'
}

// splitLines 把 buf 切成行，base 是 buf[0] 在文件里的偏移。
// **最后一行没有换行符就丢掉**——那是还没写完的一行，解析它只会得到半条 JSON，
// 而下一轮从它的行首重读一次就完整了。
func splitLines(buf []byte, base int64) []transcriptLine {
	out := make([]transcriptLine, 0, bytes.Count(buf, []byte{'\n'}))
	at := base
	for {
		i := bytes.IndexByte(buf, '\n')
		if i < 0 {
			break
		}
		line := bytes.TrimRight(buf[:i], "\r")
		out = append(out, transcriptLine{At: at, Text: line})
		at += int64(i) + 1
		buf = buf[i+1:]
	}
	return out
}

// lastComplete 返回「读到哪儿了」：最后一行的行尾。没有完整行时退回 fallback，
// 免得把没写完的半行也算成已读，下一轮就永远看不到它了。
func lastComplete(lines []transcriptLine, fallback int64) int64 {
	if len(lines) == 0 {
		return fallback
	}
	l := lines[len(lines)-1]
	return l.At + int64(len(l.Text)) + 1
}
