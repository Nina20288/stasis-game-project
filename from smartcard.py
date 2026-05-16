from smartcard.scard import (
    SCARD_SCOPE_USER,
    SCARD_SHARE_SHARED,
    SCARD_PROTOCOL_T0,
    SCARD_PROTOCOL_T1,
    SCARD_UNPOWER_CARD,
    SCARD_S_SUCCESS,
    SCardEstablishContext,
    SCardListReaders,
    SCardConnect,
    SCardStatus,
    SCardTransmit,
    SCardDisconnect,
    SCardReleaseContext,
    SCardGetErrorMessage,
)
from smartcard.util import toHexString

def check(rv, msg):
    if rv != SCARD_S_SUCCESS:
        raise RuntimeError(f"{msg}: {SCardGetErrorMessage(rv)}")

def main():
    # Establish the PC/SC context
    rv, hcontext = SCardEstablishContext(SCARD_SCOPE_USER)
    check(rv, "SCardEstablishContext failed")

    try:
        # List readers
        rv, readers = SCardListReaders(hcontext, [])
        check(rv, "SCardListReaders failed")

        if not readers:
            print("No smart card readers found.")
            return

        print("Readers found:")
        for r in readers:
            print(" -", r)

        reader = readers[0]
        print("\nUsing:", reader)

        # Connect to the first reader
        rv, hcard, active_protocol = SCardConnect(
            hcontext,
            reader,
            SCARD_SHARE_SHARED,
            SCARD_PROTOCOL_T0 | SCARD_PROTOCOL_T1,
        )
        check(rv, "SCardConnect failed")

        try:
            # Read ATR / status
            rv, reader_name, state, protocol, atr = SCardStatus(hcard)
            check(rv, "SCardStatus failed")
            print("ATR:", toHexString(atr))
            print("Protocol:", protocol)

            # Example APDU: SELECT Master File (ISO 7816)
            apdu = [0x00, 0xA4, 0x00, 0x00, 0x02, 0x3F, 0x00]
            rv, response = SCardTransmit(hcard, active_protocol, apdu)
            check(rv, "SCardTransmit failed")
            print("APDU response:", toHexString(response))

        finally:
            SCardDisconnect(hcard, SCARD_UNPOWER_CARD)

    finally:
        SCardReleaseContext(hcontext)

if __name__ == "__main__":
    main()