from concurrent.futures import ThreadPoolExecutor

import cloudinary
import cloudinary.uploader

from app.config import settings


_executor = ThreadPoolExecutor(max_workers=4)


def _upload(data: bytes, filename: str, resource_type: str) -> str:
    if not all((settings.cloudinary_cloud_name, settings.cloudinary_api_key, settings.cloudinary_api_secret)):
        raise RuntimeError("Cloudinary credentials are missing; configure them in backend/.env.")
    cloudinary.config(
        cloud_name=settings.cloudinary_cloud_name,
        api_key=settings.cloudinary_api_key,
        api_secret=settings.cloudinary_api_secret,
        secure=True,
    )
    result = cloudinary.uploader.upload(
        data,
        public_id=f"nagarseva/{filename}",
        resource_type=resource_type,
        overwrite=False,
    )
    url = result.get("secure_url")
    if not url:
        raise RuntimeError("Cloudinary did not return a media URL.")
    return url


async def upload(data: bytes, filename: str, resource_type: str) -> str:
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, _upload, data, filename, resource_type)
