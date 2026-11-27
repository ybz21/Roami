//go:build windows

package terminal

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
)

var (
	kernel32                 = windows.NewLazySystemDLL("kernel32.dll")
	procCreatePseudoConsole  = kernel32.NewProc("CreatePseudoConsole")
	procResizePseudoConsole  = kernel32.NewProc("ResizePseudoConsole")
	procClosePseudoConsole   = kernel32.NewProc("ClosePseudoConsole")
	procReleasePseudoConsole = kernel32.NewProc("ReleasePseudoConsole")
)

const (
	procThreadAttributePseudoconsole = 0x00020016
	stillActiveExitCode              = 259
)

// WindowsBackend implements TerminalBackend using native Windows ConPTY and Job Objects.
type WindowsBackend struct{}

// NewBackend returns the native TerminalBackend for the current operating system.
func NewBackend() TerminalBackend { return WindowsBackend{} }

func (WindowsBackend) Capabilities() Capabilities {
	return Capabilities{
		MemoryLimit:    true,
		Pause:          false,
		ProcessInspect: true,
		CurrentDir:     false,
		Signals:        false,
	}
}

func (WindowsBackend) ProcessIdentity(pid int) (string, error) {
	if pid < 1 {
		return "", fmt.Errorf("terminal: invalid pid %d", pid)
	}
	h, err := windows.OpenProcess(windows.PROCESS_QUERY_LIMITED_INFORMATION, false, uint32(pid))
	if err != nil {
		return "", err
	}
	defer windows.CloseHandle(h)
	var creation, exit, kernel, user windows.Filetime
	if err := windows.GetProcessTimes(h, &creation, &exit, &kernel, &user); err != nil {
		return "", err
	}
	return fmt.Sprintf("windows:%d:%d:%d", pid, creation.HighDateTime, creation.LowDateTime), nil
}

func (WindowsBackend) CurrentDir(_ int) (string, error) { return "", ErrUnsupported }

func (WindowsBackend) Start(ctx context.Context, spec LaunchSpec) (Terminal, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if err := procCreatePseudoConsole.Find(); err != nil {
		return nil, fmt.Errorf("terminal: ConPTY unavailable: %w", err)
	}
	cols, rows := normalizeSize(spec.Cols, spec.Rows)

	var inRead, inWrite, outRead, outWrite windows.Handle
	if err := windows.CreatePipe(&inRead, &inWrite, nil, 0); err != nil {
		return nil, fmt.Errorf("terminal: create input pipe: %w", err)
	}
	if err := windows.CreatePipe(&outRead, &outWrite, nil, 0); err != nil {
		_ = windows.CloseHandle(inRead)
		_ = windows.CloseHandle(inWrite)
		return nil, fmt.Errorf("terminal: create output pipe: %w", err)
	}

	coord := uintptr(uint32(cols) | (uint32(rows) << 16))
	var hpcon windows.Handle
	r1, _, _ := procCreatePseudoConsole.Call(coord, uintptr(inRead), uintptr(outWrite), 0, uintptr(unsafe.Pointer(&hpcon)))
	if r1 != 0 {
		_ = windows.CloseHandle(inRead)
		_ = windows.CloseHandle(inWrite)
		_ = windows.CloseHandle(outRead)
		_ = windows.CloseHandle(outWrite)
		return nil, fmt.Errorf("terminal: CreatePseudoConsole failed: 0x%x", r1)
	}
	// Close the console-side ends now that ConPTY owns duplicates of them.
	_ = windows.CloseHandle(inRead)
	_ = windows.CloseHandle(outWrite)

	attrList, err := windows.NewProcThreadAttributeList(1)
	if err != nil {
		_, _, _ = procClosePseudoConsole.Call(uintptr(hpcon))
		_ = windows.CloseHandle(inWrite)
		_ = windows.CloseHandle(outRead)
		return nil, err
	}
	defer attrList.Delete()
	if err := attrList.Update(procThreadAttributePseudoconsole, unsafe.Pointer(hpcon), unsafe.Sizeof(hpcon)); err != nil {
		_, _, _ = procClosePseudoConsole.Call(uintptr(hpcon))
		_ = windows.CloseHandle(inWrite)
		_ = windows.CloseHandle(outRead)
		return nil, err
	}

	exe := spec.Exe
	if exe == "" {
		exe = DefaultShell()
	}
	cmdLine := buildWindowsCommandLine(exe, spec.Args)
	cmdLinePtr, err := windows.UTF16PtrFromString(cmdLine)
	if err != nil {
		_, _, _ = procClosePseudoConsole.Call(uintptr(hpcon))
		_ = windows.CloseHandle(inWrite)
		_ = windows.CloseHandle(outRead)
		return nil, err
	}
	var cwdPtr *uint16
	if spec.Cwd != "" {
		cwdPtr, err = windows.UTF16PtrFromString(spec.Cwd)
		if err != nil {
			_, _, _ = procClosePseudoConsole.Call(uintptr(hpcon))
			_ = windows.CloseHandle(inWrite)
			_ = windows.CloseHandle(outRead)
			return nil, err
		}
	}
	envBlock := buildWindowsEnvBlock(mergeEnv(os.Environ(), spec.Env))

	var si windows.StartupInfoEx
	si.Cb = uint32(unsafe.Sizeof(si))
	si.ProcThreadAttributeList = attrList.List()

	var pi windows.ProcessInformation
	flags := uint32(windows.EXTENDED_STARTUPINFO_PRESENT | windows.CREATE_SUSPENDED | windows.CREATE_UNICODE_ENVIRONMENT)
	err = windows.CreateProcess(nil, cmdLinePtr, nil, nil, false, flags, &envBlock[0], cwdPtr, &si.StartupInfo, &pi)
	if err != nil {
		_, _, _ = procClosePseudoConsole.Call(uintptr(hpcon))
		_ = windows.CloseHandle(inWrite)
		_ = windows.CloseHandle(outRead)
		return nil, fmt.Errorf("terminal: CreateProcess: %w", err)
	}

	job, jobErr := createKillOnCloseJob()
	if jobErr == nil {
		if assignErr := windows.AssignProcessToJobObject(job, pi.Process); assignErr != nil {
			_ = windows.CloseHandle(job)
			job = 0
		}
	}

	if _, resumeErr := windows.ResumeThread(pi.Thread); resumeErr != nil {
		_ = windows.TerminateProcess(pi.Process, 1)
		_ = windows.CloseHandle(pi.Thread)
		_ = windows.CloseHandle(pi.Process)
		if job != 0 {
			_ = windows.CloseHandle(job)
		}
		_, _, _ = procClosePseudoConsole.Call(uintptr(hpcon))
		_ = windows.CloseHandle(inWrite)
		_ = windows.CloseHandle(outRead)
		return nil, fmt.Errorf("terminal: ResumeThread: %w", resumeErr)
	}
	_ = windows.CloseHandle(pi.Thread)

	t := &windowsTerminal{
		hpcon:    hpcon,
		inFile:   os.NewFile(uintptr(inWrite), "conpty-in"),
		outFile:  os.NewFile(uintptr(outRead), "conpty-out"),
		proc:     pi.Process,
		job:      job,
		pid:      int(pi.ProcessId),
		waitDone: make(chan struct{}),
	}
	go t.reap()
	return t, nil
}

func createKillOnCloseJob() (windows.Handle, error) {
	job, err := windows.CreateJobObject(nil, nil)
	if err != nil {
		return 0, err
	}
	info := windows.JOBOBJECT_EXTENDED_LIMIT_INFORMATION{}
	info.BasicLimitInformation.LimitFlags = windows.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
	_, err = windows.SetInformationJobObject(job, windows.JobObjectExtendedLimitInformation, uintptr(unsafe.Pointer(&info)), uint32(unsafe.Sizeof(info)))
	if err != nil {
		_ = windows.CloseHandle(job)
		return 0, err
	}
	return job, nil
}

// buildWindowsCommandLine safely routes .cmd/.bat wrappers through cmd.exe while passing native executables directly.
func buildWindowsCommandLine(exe string, args []string) string {
	ext := strings.ToLower(filepath.Ext(exe))
	if ext == ".cmd" || ext == ".bat" {
		full := append([]string{"/d", "/c", exe}, args...)
		return windows.ComposeCommandLine(append([]string{"cmd.exe"}, full...))
	}
	return windows.ComposeCommandLine(append([]string{exe}, args...))
}

func buildWindowsEnvBlock(env []string) []uint16 {
	var b strings.Builder
	for _, kv := range env {
		b.WriteString(kv)
		b.WriteByte(0)
	}
	b.WriteByte(0)
	block, _ := windows.UTF16FromString(b.String())
	if len(block) < 2 {
		return []uint16{0, 0}
	}
	return block
}

type windowsTerminal struct {
	hpcon   windows.Handle
	inFile  *os.File
	outFile *os.File
	proc    windows.Handle
	job     windows.Handle
	pid     int

	mu     sync.Mutex
	closed bool

	waitDone chan struct{}
	exit     ExitResult
	waitErr  error
}

func (t *windowsTerminal) reap() {
	defer close(t.waitDone)
	event, err := windows.WaitForSingleObject(t.proc, windows.INFINITE)
	if err != nil || event != windows.WAIT_OBJECT_0 {
		t.exit = ExitResult{Unknown: true, Reason: fmt.Sprintf("WaitForSingleObject event=%d err=%v", event, err)}
		t.waitErr = err
		return
	}
	var code uint32
	if err := windows.GetExitCodeProcess(t.proc, &code); err != nil {
		t.exit = ExitResult{Unknown: true, Reason: fmt.Sprintf("GetExitCodeProcess: %v", err)}
		t.waitErr = err
		return
	}
	if code == stillActiveExitCode {
		t.exit = ExitResult{Unknown: true, Reason: "process still active after wait"}
		return
	}
	t.exit = ExitResult{Exited: true, ExitCode: int(int32(code))}
	// ReleasePseudoConsole on Win11 24H2 lets output drain cleanly to EOF once clients exit.
	if procReleasePseudoConsole.Find() == nil {
		_, _, _ = procReleasePseudoConsole.Call(uintptr(t.hpcon))
	}
}

func (t *windowsTerminal) PID() int { return t.pid }

func (t *windowsTerminal) Read(p []byte) (int, error) {
	n, err := t.outFile.Read(p)
	if err != nil && err != io.EOF {
		return n, err
	}
	return n, err
}

func (t *windowsTerminal) Write(p []byte) (int, error) {
	t.mu.Lock()
	closed := t.closed
	t.mu.Unlock()
	if closed {
		return 0, ErrClosed
	}
	return t.inFile.Write(p)
}

func (t *windowsTerminal) Resize(cols, rows uint16) error {
	t.mu.Lock()
	closed := t.closed
	t.mu.Unlock()
	if closed {
		return ErrClosed
	}
	cols, rows = normalizeSize(cols, rows)
	coord := uintptr(uint32(cols) | (uint32(rows) << 16))
	r1, _, _ := procResizePseudoConsole.Call(uintptr(t.hpcon), coord)
	if r1 != 0 {
		return fmt.Errorf("terminal: ResizePseudoConsole failed: 0x%x", r1)
	}
	return nil
}

func (t *windowsTerminal) Terminate(ctx context.Context, grace time.Duration) error {
	if grace <= 0 {
		grace = 2 * time.Second
	}
	// Send Ctrl+C first for a graceful attempt before terminating the Job tree.
	_, _ = t.Write([]byte{0x03})
	timer := time.NewTimer(grace)
	defer timer.Stop()
	select {
	case <-t.waitDone:
		return nil
	case <-timer.C:
	case <-ctx.Done():
	}
	if t.job != 0 {
		_ = windows.TerminateJobObject(t.job, 1)
	} else {
		_ = windows.TerminateProcess(t.proc, 1)
	}
	select {
	case <-t.waitDone:
		return nil
	case <-time.After(2 * time.Second):
		return fmt.Errorf("terminal: process %d did not exit after Terminate", t.pid)
	}
}

func (t *windowsTerminal) Wait() (ExitResult, error) {
	<-t.waitDone
	return t.exit, t.waitErr
}

func (t *windowsTerminal) Close() error {
	t.mu.Lock()
	if t.closed {
		t.mu.Unlock()
		return nil
	}
	t.closed = true
	t.mu.Unlock()

	_, _, _ = procClosePseudoConsole.Call(uintptr(t.hpcon))
	_ = t.inFile.Close()
	_ = t.outFile.Close()
	if t.job != 0 {
		_ = windows.CloseHandle(t.job)
	}
	_ = windows.CloseHandle(t.proc)
	return nil
}
