import time

from smartcard.scard import (
    SCARD_SCOPE_USER,
    SCARD_SHARE_SHARED,
    SCARD_PROTOCOL_T0,
    SCARD_PROTOCOL_T1,
    SCARD_PCI_T0,
    SCARD_PCI_T1,
    SCARD_LEAVE_CARD,
    SCARD_UNPOWER_CARD,
    SCARD_S_SUCCESS,
    SCARD_STATE_UNAWARE,
    SCARD_STATE_PRESENT,
    SCARD_E_TIMEOUT,
    SCardEstablishContext,
    SCardListReaders,
    SCardConnect,
    SCardStatus,
    SCardTransmit,
    SCardDisconnect,
    SCardReleaseContext,
    SCardGetStatusChange,
    SCardGetErrorMessage,
)
from smartcard.util import toHexString

class PCSCError(RuntimeError):
    pass


def check(rv, msg):
    if rv != SCARD_S_SUCCESS:
        raise PCSCError(f"{msg}: {SCardGetErrorMessage(rv)}")


def establish_context():
    rv, hcontext = SCardEstablishContext(SCARD_SCOPE_USER)
    check(rv, "SCardEstablishContext failed")
    return hcontext


def list_readers(hcontext):
    rv, readers = SCardListReaders(hcontext, [])
    check(rv, "SCardListReaders failed")
    return readers


def wait_for_card(hcontext, reader, timeout=0):
    import time

    start_time = time.time()
    readerstates = [(reader, SCARD_STATE_UNAWARE)]

    while True:
        if timeout:
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                return False
            timeout_ms = int(min(timeout - elapsed, 1) * 1000)
        else:
            timeout_ms = 1000

        rv, newstates = SCardGetStatusChange(
            hcontext,
            timeout_ms,
            readerstates,
        )
        if rv == SCARD_E_TIMEOUT:
            continue
        check(rv, "SCardGetStatusChange failed")

        _, eventstate, _ = newstates[0]
        if eventstate & SCARD_STATE_PRESENT:
            return True

        readerstates = [(reader, eventstate)]


def connect(hcontext, reader):
    rv, hcard, active_protocol = SCardConnect(
        hcontext,
        reader,
        SCARD_SHARE_SHARED,
        SCARD_PROTOCOL_T0 | SCARD_PROTOCOL_T1,
    )
    check(rv, "SCardConnect failed")
    return hcard, active_protocol


def connect_with_retry(hcontext, reader, retries=3, delay=1):
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return connect(hcontext, reader)
        except PCSCError as exc:
            last_error = exc
            if attempt == retries:
                raise
            time.sleep(delay)
    raise last_error


def disconnect(hcard):
    # Use LEAVE_CARD instead of UNPOWER_CARD so the reader/card can be reused
    # immediately on the next run without a long cooldown.
    SCardDisconnect(hcard, SCARD_LEAVE_CARD)


def release_context(hcontext):
    SCardReleaseContext(hcontext)


def status(hcard):
    rv, reader_name, state, protocol, atr = SCardStatus(hcard)
    check(rv, "SCardStatus failed")
    return reader_name, state, protocol, atr


def transmit(hcard, protocol, apdu):
    send_pci = SCARD_PCI_T0 if protocol == SCARD_PROTOCOL_T0 else SCARD_PCI_T1
    rv, response = SCardTransmit(hcard, send_pci, apdu)
    check(rv, "SCardTransmit failed")
    return response

def transmit_apdu(hcard, protocol, apdu, label):
    print(f"\n--- {label} ---")
    print("TX:", toHexString(apdu))

    rv, response = SCardTransmit(hcard, protocol, apdu)
    check(rv, f"{label} transmit failed")

    print("RX:", toHexString(response))

    if len(response) >= 2:
        data = response[:-2]
        sw1, sw2 = response[-2:]
        print("Data:", toHexString(data))
        print(f"SW1={sw1:02X} SW2={sw2:02X}")

    return response