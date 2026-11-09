package okr

// MemoryCapacityError leaves current bytes and operation history unchanged.
type MemoryCapacityError struct {
	CurrentBytes   int
	RequestedBytes int
	LimitBytes     int
}

func (e *MemoryCapacityError) Error() string { return "OKR_MEMORY_CAPACITY" }
func (e *MemoryCapacityError) Unwrap() error { return ErrInvalid }

func memoryCapacity(current, requested int) error {
	return &MemoryCapacityError{CurrentBytes: current, RequestedBytes: requested, LimitBytes: maxMemory}
}
