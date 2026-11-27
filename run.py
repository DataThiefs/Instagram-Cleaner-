import os
import socket
import uvicorn


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def main() -> None:
    host = os.environ.get("INSCLEANER_HOST", "0.0.0.0")
    port = int(os.environ.get("INSCLEANER_PORT", "8000"))
    lan_ip = get_lan_ip()

    print("=" * 56)
    print("  InsCleaner — Instagram Story & DM Cleaner")
    print("=" * 56)
    print(f"  PC Tarayici  : http://127.0.0.1:{port}")
    print(f"  Mobil (Wi-Fi): http://{lan_ip}:{port}")
    print("  (Telefonunuz ayni Wi-Fi agindaysa yukaridaki adresi")
    print("   acip 'Ana Ekrana Ekle' ile uygulama gibi kullanabilirsiniz)")
    print("=" * 56)

    uvicorn.run("backend.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
