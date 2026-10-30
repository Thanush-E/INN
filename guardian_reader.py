
import json
import time
import requests
import serial
from serial import SerialException

SERIAL_PORT = "COM18"
BAUD_RATE = 115200
API_URL = "http://127.0.0.1:5000/api/telemetry"

RECONNECT_DELAY = 3
HTTP_TIMEOUT = 3


def main():
    connection = None

    print("Guardian Reader starting...")
    print(f"Serial port: {SERIAL_PORT}")
    print(f"Baud rate: {BAUD_RATE}")

    while True:
        try:
            if connection is None or not connection.is_open:
                print(f"Connecting to Guardian on {SERIAL_PORT}...")
                connection = serial.Serial(
                    SERIAL_PORT,
                    BAUD_RATE,
                    timeout=1
                )
                time.sleep(2)
                print("Guardian connected.")

            raw_line = connection.readline().decode(
                "utf-8", errors="ignore"
            ).strip()

            if not raw_line:
                continue

            if not raw_line.startswith("DASH:"):
                continue

            json_text = raw_line[len("DASH:"):]

            try:
                telemetry = json.loads(json_text)
            except json.JSONDecodeError:
                print("Invalid JSON received:", json_text)
                continue

            if not isinstance(telemetry, dict):
                continue

            # Support both the current guardian_state field
            # and the older state field.
            guardian_state = telemetry.get(
                "guardian_state",
                telemetry.get("state", "SEARCHING")
            )

            payload = {
                "guardian_state": guardian_state,
                "child_state": telemetry.get("child_state", "SAFE"),
                "rssi": telemetry.get("rssi"),
                "buzzer": telemetry.get("buzzer", False)
            }

            try:
                response = requests.post(
                    API_URL,
                    json=payload,
                    timeout=HTTP_TIMEOUT
                )

                if response.ok:
                    print("Telemetry sent:", payload)
                else:
                    print(
                        "Dashboard rejected telemetry:",
                        response.status_code,
                        response.text
                    )

            except requests.RequestException as error:
                print("Flask connection error:", error)

        except SerialException as error:
            print("Serial connection error:", error)

            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass

            connection = None
            time.sleep(RECONNECT_DELAY)

        except KeyboardInterrupt:
            print("\nGuardian Reader stopped.")
            break

        except Exception as error:
            print("Unexpected error:", error)
            time.sleep(1)

    if connection is not None and connection.is_open:
        connection.close()


if __name__ == "__main__":
    main()
