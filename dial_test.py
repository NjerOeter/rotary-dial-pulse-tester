#!/usr/bin/env python3
"""Measure an isolated rotary-dial pulse contact with Raspberry Pi GPIO.

IMPORTANT: Never connect GPIO directly to a live analog telephone line,
FRITZ!Box FON port, TAE connector, or the phone's a/b line.

Default wiring:
    GPIO17 / physical pin 11 -> 1 kOhm -> pulse contact -> GND / pin 9
"""

import statistics
import threading
import time
from gpiozero import Button
from gpiozero.pins.lgpio import LGPIOFactory

GPIO = 17
DIGIT_END_MS = 250
GLITCH_GAP_MS = 8
MIN_PULSE_MS = 15

factory = LGPIOFactory(chip=0)
nsi = Button(GPIO, pull_up=True, bounce_time=None, pin_factory=factory)

lock = threading.Lock()
pulse_start = None
pending_gap = None
last_close = None
pulses = []


def contact_opened():
    global pulse_start, pending_gap
    now = time.monotonic_ns()
    with lock:
        if pulse_start is not None:
            return
        pending_gap = None if last_close is None else (now-last_close)/1_000_000
        pulse_start = now


def contact_closed():
    global pulse_start, pending_gap, last_close
    now = time.monotonic_ns()
    with lock:
        if pulse_start is None:
            return
        pulses.append({'open': (now-pulse_start)/1_000_000, 'gap': pending_gap})
        last_close = now
        pulse_start = None
        pending_gap = None


def merge_short_gaps(raw):
    merged=[]
    for p in raw:
        if merged and p['gap'] is not None and p['gap'] < GLITCH_GAP_MS:
            merged[-1]['open'] += p['gap'] + p['open']
            merged[-1]['glitch'] = True
        else:
            merged.append({'open':p['open'],'gap':p['gap'],'glitch':False})
    return merged


def digit_from_count(count):
    if count == 10:
        return '0'
    if 1 <= count <= 9:
        return str(count)
    return '?'


def print_digit(raw):
    merged = merge_short_gaps(raw)
    valid = [p for p in merged if p['open'] >= MIN_PULSE_MS]
    count = len(valid)
    digit = digit_from_count(count)
    opens = [p['open'] for p in valid]
    gaps = [p['gap'] for p in valid[1:] if p['gap'] is not None]

    print('
' + '='*60)
    print(f'Detected digit: {digit}')
    print(f'Pulse count:    {count}
')
    if opens:
        print('Open times:')
        print('  ' + '  '.join(f'{x:6.1f}' for x in opens) + ' ms')
    if gaps:
        print('Closed times:')
        print('  ' + '  '.join(f'{x:6.1f}' for x in gaps) + ' ms')
    if opens:
        print(f'
Open mean:      {statistics.mean(opens):6.1f} ms')
    if gaps:
        mo = statistics.mean(opens)
        mc = statistics.mean(gaps)
        period = mo + mc
        print(f'Closed mean:    {mc:6.1f} ms')
        print(f'Pulse period:   {period:6.1f} ms')
        print(f'Pulse rate:     {1000/period:6.2f} pulses/s')

    glitches = sum(p['glitch'] for p in merged)
    if glitches:
        print(f'
WARNING: {glitches} possible contact-bounce or edge-artifact event(s)')

    print('
Raw transitions:')
    for i,p in enumerate(raw,1):
        gap = '-' if p['gap'] is None else f"{p['gap']:.2f} ms"
        print(f"  {i:2d}: open {p['open']:7.2f} ms   preceding closed gap {gap}")


# pull_up=True means closed contact = LOW = pressed
nsi.when_released = contact_opened
nsi.when_pressed = contact_closed

print('Rotary dial tester')
print('------------------')
print(f'GPIO{GPIO} = physical pin 11')
print('GND    = physical pin 9
')
print('At rest the pulse contact should be CLOSED.')
print(f"Current state: {'CLOSED' if nsi.is_pressed else 'OPEN'}
")
print('Dial digits now. Ctrl+C to quit.')

try:
    while True:
        time.sleep(0.01)
        finished = None
        with lock:
            if pulses and pulse_start is None and last_close is not None:
                elapsed_ms = (time.monotonic_ns()-last_close)/1_000_000
                if elapsed_ms >= DIGIT_END_MS:
                    finished = pulses.copy()
                    pulses.clear()
                    last_close = None
        if finished:
            print_digit(finished)
except KeyboardInterrupt:
    print('
Stopped.')
finally:
    nsi.close()
    factory.close()
