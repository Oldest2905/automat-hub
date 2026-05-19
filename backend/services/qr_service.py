"""
services/qr_service.py
QR code generation and S3 upload for DCP verification.
"""

import qrcode
import boto3
import io
from backend.config import settings


async def generate_qr_code(data: str, dcp_id: str) -> str:
    """
    Generate QR code for DCP verification URL.
    Uploads to S3 and returns public URL.
    """
    try:
        # Generate QR code
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(data)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")

        # Save to bytes buffer
        buffer = io.BytesIO()
        img.save(buffer, format='PNG')
        buffer.seek(0)

        # Upload to S3
        if settings.AWS_ACCESS_KEY_ID:
            s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
                aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
                region_name=settings.AWS_REGION
            )

            s3_key = f"qr-codes/{dcp_id}.png"
            s3_client.upload_fileobj(
                buffer,
                settings.AWS_BUCKET_NAME,
                s3_key,
                ExtraArgs={'ContentType': 'image/png', 'ACL': 'public-read'}
            )

            return f"https://{settings.AWS_BUCKET_NAME}.s3.{settings.AWS_REGION}.amazonaws.com/{s3_key}"

        # If no S3 configured return the verification URL directly
        return data

    except Exception as e:
        print(f"QR generation error: {e}")
        return data
