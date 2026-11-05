package cron

import (
	"fmt"
	"strconv"
	"strings"
	"time"
)

// 排期用标准 5 段 cron 表达式:「分 时 日 月 周」。语义与传统 crontab 一致——
// 按墙钟匹配触发(不是"距上次 N 之后"),最小粒度 1 分钟。周(dow)0-6,0=周日,
// 7 也当周日。日(dom)与周(dow)都受限(非 *)时按 OR 匹配(crontab 惯例)。
//
// 每段支持:*  a  a-b  a,b,c  */n  a-b/n(可逗号组合)。例:
//
//	*/5 * * * *     每 5 分钟
//	30 9 * * *      每天 09:30
//	0 9 */3 * *     每隔 3 天(按月内日号)的 09:00
//	0 18 * * 1-5    工作日 18:00
type cronSchedule struct {
	min, hour, dom, month, dow uint64 // 各段的位掩码
	domStar, dowStar           bool   // 该段是否为 "*"(决定日/周的 OR 语义)
}

// parseCron 解析并校验一条 5 段 cron 表达式。
func parseCron(expr string) (*cronSchedule, error) {
	fields := strings.Fields(strings.TrimSpace(expr))
	if len(fields) != 5 {
		return nil, fmt.Errorf("cron 需要 5 段「分 时 日 月 周」,得到 %d 段: %q", len(fields), expr)
	}
	var s cronSchedule
	var err error
	if s.min, _, err = parseField(fields[0], 0, 59); err != nil {
		return nil, fmt.Errorf("分段 %w", err)
	}
	if s.hour, _, err = parseField(fields[1], 0, 23); err != nil {
		return nil, fmt.Errorf("时段 %w", err)
	}
	if s.dom, s.domStar, err = parseField(fields[2], 1, 31); err != nil {
		return nil, fmt.Errorf("日段 %w", err)
	}
	if s.month, _, err = parseField(fields[3], 1, 12); err != nil {
		return nil, fmt.Errorf("月段 %w", err)
	}
	// 周段按 0-7 解析后把「7(周日)」并回 bit0,统一 0=周日
	if s.dow, s.dowStar, err = parseField(fields[4], 0, 7); err != nil {
		return nil, fmt.Errorf("周段 %w", err)
	}
	if s.dow&(1<<7) != 0 {
		s.dow = (s.dow &^ (1 << 7)) | (1 << 0)
	}
	return &s, nil
}

// parseField 把一段 cron 字段解析成 [lo,hi] 上的位掩码;isStar 记录该段是否 "*"。
func parseField(spec string, lo, hi int) (mask uint64, isStar bool, err error) {
	spec = strings.TrimSpace(spec)
	if spec == "" {
		return 0, false, fmt.Errorf("为空")
	}
	isStar = spec == "*"
	for _, tok := range strings.Split(spec, ",") {
		rangePart, step := tok, 1
		if i := strings.Index(tok, "/"); i >= 0 {
			rangePart = tok[:i]
			if step, err = strconv.Atoi(tok[i+1:]); err != nil || step < 1 {
				return 0, false, fmt.Errorf("步进非法: %q", tok)
			}
		}
		var start, end int
		switch {
		case rangePart == "*":
			start, end = lo, hi
		case strings.Contains(rangePart, "-"):
			ps := strings.SplitN(rangePart, "-", 2)
			if start, err = strconv.Atoi(strings.TrimSpace(ps[0])); err != nil {
				return 0, false, fmt.Errorf("区间起点非法: %q", tok)
			}
			if end, err = strconv.Atoi(strings.TrimSpace(ps[1])); err != nil {
				return 0, false, fmt.Errorf("区间终点非法: %q", tok)
			}
		default:
			if start, err = strconv.Atoi(rangePart); err != nil {
				return 0, false, fmt.Errorf("数值非法: %q", tok)
			}
			end = start
		}
		if start < lo || end > hi || start > end {
			return 0, false, fmt.Errorf("%q 越界或区间反了(允许 %d-%d)", tok, lo, hi)
		}
		for v := start; v <= end; v += step {
			mask |= 1 << uint(v)
		}
	}
	return mask, isStar, nil
}

// next 返回严格晚于 from 的下一个触发时刻(秒归零)。逐字段跳跃而非逐分钟扫,
// 命中不了就把无关的低位归零再进位,一年内找不到则报错(近乎不可能的坏表达式)。
func (s *cronSchedule) next(from time.Time) (time.Time, error) {
	t := from.Truncate(time.Minute).Add(time.Minute)
	limit := t.AddDate(1, 0, 1) // 一年零一天上限:防坏表达式死循环
	for t.Before(limit) {
		if s.month&(1<<uint(int(t.Month()))) == 0 {
			t = time.Date(t.Year(), t.Month(), 1, 0, 0, 0, 0, t.Location()).AddDate(0, 1, 0)
			continue
		}
		if !s.dayMatch(t) {
			t = time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, t.Location()).AddDate(0, 0, 1)
			continue
		}
		if s.hour&(1<<uint(t.Hour())) == 0 {
			t = time.Date(t.Year(), t.Month(), t.Day(), t.Hour(), 0, 0, 0, t.Location()).Add(time.Hour)
			continue
		}
		if s.min&(1<<uint(t.Minute())) == 0 {
			t = t.Add(time.Minute)
			continue
		}
		return t, nil
	}
	return time.Time{}, fmt.Errorf("一年内没有匹配的触发时刻,请检查表达式")
}

// dayMatch 实现 crontab 的日/周 OR 语义。
func (s *cronSchedule) dayMatch(t time.Time) bool {
	domOK := s.dom&(1<<uint(t.Day())) != 0
	dowOK := s.dow&(1<<uint(int(t.Weekday()))) != 0
	switch {
	case s.domStar && s.dowStar:
		return true
	case s.domStar: // 只限了周
		return dowOK
	case s.dowStar: // 只限了日
		return domOK
	default: // 日、周都限了 → OR
		return domOK || dowOK
	}
}

// validateCron 仅校验表达式合法性(cron.add / cron.preview 入口用)。
func validateCron(expr string) error {
	_, err := parseCron(expr)
	return err
}

// nextRun 解析任务的 cron 表达式并返回晚于 from 的下一次触发。
func nextRun(j Job, from time.Time) (time.Time, error) {
	s, err := parseCron(j.Cron)
	if err != nil {
		return time.Time{}, err
	}
	location, err := scheduleLocation(j.Timezone)
	if err != nil {
		return time.Time{}, err
	}
	return s.next(from.In(location))
}
