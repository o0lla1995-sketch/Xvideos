FROM python:3.11-slim

# تثبيت الحزم الأساسية ونظام تشغيل الوسائط ffmpeg لضمان عمل yt-dlp بكفاءة
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# تحديد مجلد العمل داخل الحاوية
WORKDIR /app

# نسخ ملف المتطلبات وتثبيتها أولاً لاستغلال التخزين المؤقت (Cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# نسخ باقي ملفات المشروع إلى الحاوية
COPY . .

# فتح المنفذ الذي يعمل عليه تطبيق Flask
EXPOSE 3000

# أمر تشغيل السكربت تلقائياً في وضع الخادم
CMD ["python", "x-video-extractor.py", "--server"]
