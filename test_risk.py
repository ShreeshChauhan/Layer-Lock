
import asyncio
import httpx

API = "http://127.0.0.1:8000"


async def main():
    async with httpx.AsyncClient() as client:
        await client.post(f"{API}/risk/arm")

        for second in range(8):
            response = await client.post(
                f"{API}/risk/update",
                json={
                    "camera_confidence": 95,
                    "vibration": 90,
                    "sound": 85,
                    "filament_runout": False
                }
            )

            data = response.json()

            print(
                f"Second {second}: "
                f"Risk={data['risk_score']}%, "
                f"State={data['state']}, "
                f"Paused={data['paused']}"
            )

            if data["paused"]:
                print("Automatic pause triggered!")
                break

            await asyncio.sleep(1)


asyncio.run(main())
