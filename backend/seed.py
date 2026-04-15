import asyncio

from app.services.seed import seed_demo_data


if __name__ == "__main__":
    asyncio.run(seed_demo_data())
