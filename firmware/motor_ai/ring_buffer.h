#ifndef RING_BUFFER_H
#define RING_BUFFER_H

#include <Arduino.h>

template <typename T, size_t Size>
class RingBuffer {
private:
    volatile T _buffer[Size];
    volatile size_t _head;
    volatile size_t _tail;
    const size_t _mask;
    portMUX_TYPE _mux = portMUX_INITIALIZER_UNLOCKED;

    // Diagnostics metrics
    volatile size_t _max_occupancy = 0;
    volatile size_t _overrun_count = 0;

public:
    RingBuffer() : _head(0), _tail(0), _mask(Size - 1) {}

    bool push(T val) {
        bool success = false;
        portENTER_CRITICAL(&_mux);
        size_t next_head = (_head + 1) & _mask;
        if (next_head != _tail) {
            _buffer[_head] = val;
            _head = next_head;
            success = true;

            // Track maximum occupancy high-watermark
            size_t occupancy = (_head - _tail) & _mask;
            if (occupancy > _max_occupancy) {
                _max_occupancy = occupancy;
            }
        } else {
            // Increment overrun count if buffer is full
            _overrun_count++;
        }
        portEXIT_CRITICAL(&_mux);
        return success;
    }

    bool pop(T &val) {
        bool success = false;
        portENTER_CRITICAL(&_mux);
        if (_tail != _head) {
            val = _buffer[_tail];
            _tail = (_tail + 1) & _mask;
            success = true;
        }
        portEXIT_CRITICAL(&_mux);
        return success;
    }

    size_t available() {
        size_t count = 0;
        portENTER_CRITICAL(&_mux);
        count = (_head - _tail) & _mask;
        portEXIT_CRITICAL(&_mux);
        return count;
    }

    void clear() {
        portENTER_CRITICAL(&_mux);
        _head = 0;
        _tail = 0;
        _max_occupancy = 0;
        _overrun_count = 0;
        portEXIT_CRITICAL(&_mux);
    }

    size_t getMaxOccupancy() {
        size_t val;
        portENTER_CRITICAL(&_mux);
        val = _max_occupancy;
        portEXIT_CRITICAL(&_mux);
        return val;
    }

    size_t getOverrunCount() {
        size_t val;
        portENTER_CRITICAL(&_mux);
        val = _overrun_count;
        portEXIT_CRITICAL(&_mux);
        return val;
    }

    void resetMetrics() {
        portENTER_CRITICAL(&_mux);
        _max_occupancy = 0;
        _overrun_count = 0;
        portEXIT_CRITICAL(&_mux);
    }
};

#endif // RING_BUFFER_H
