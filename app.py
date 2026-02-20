import os
import json
import datetime
import uuid
from flask import Flask, request, jsonify, send_file, render_template, url_for, redirect
from werkzeug.utils import secure_filename
import logging

app = Flask(__name__)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Конфигурация
STORAGE_DIR = "storage"
METADATA_FILE = os.path.join(STORAGE_DIR, "metadata.json")
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'xls', 'xlsx', 'zip'}

# Создаем директорию для хранения файлов при запуске
os.makedirs(STORAGE_DIR, exist_ok=True)

# Инициализируем файл метаданных
def init_metadata():
    if not os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, 'w') as f:
            json.dump({}, f)

init_metadata()

def allowed_file(filename):
    return '.' in filename and filename.split('.')[-1].lower() in ALLOWED_EXTENSIONS

def load_metadata():
    with open(METADATA_FILE, 'r') as f:
        return json.load(f)

def save_metadata(metadata):
    with open(METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)

def get_date_subdir():
    """Создает подкаталог на основе текущей даты"""
    today = datetime.datetime.now()
    year = today.strftime("%Y")
    month = today.strftime("%m")
    day = today.strftime("%d")
    subdir = os.path.join(year, month, day)
    full_path = os.path.join(STORAGE_DIR, subdir)
    os.makedirs(full_path, exist_ok=True)
    return subdir, full_path

@app.before_request
def log_request_info():
    """Логирование запросов для отладки"""
    logger.info(f"Request: {request.method} {request.path}")
    logger.info(f"Headers: {dict(request.headers)}")

@app.route('/')
def index():
    """Главная страница с приветствием и формой загрузки"""
    try:
        files = get_files_list()
        return render_template('index.html', files=files)
    except Exception as e:
        logger.error(f"Error in index: {e}")
        return f"Error: {e}", 500

@app.route('/health')
def health():
    """Проверка здоровья приложения"""
    return jsonify({"status": "ok", "message": "App is running"})

@app.route('/upload', methods=['POST'])
def upload_file():
    """Загружает файл в облачное хранилище с метаданными"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': f'File type not allowed. Allowed: {ALLOWED_EXTENSIONS}'}), 400
        
        # Генерируем уникальное имя файла
        original_filename = secure_filename(file.filename)
        name, ext = os.path.splitext(original_filename)
        unique_id = uuid.uuid4().hex[:8]
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_filename = f"{name}_{timestamp}_{unique_id}{ext}"
        
        # Создаем подкаталог по дате
        date_subdir, storage_path = get_date_subdir()
        file_path = os.path.join(storage_path, unique_filename)
        
        # Сохраняем файл
        file.save(file_path)
        logger.info(f"File saved: {file_path}")
        
        # Получаем размер файла
        file_size = os.path.getsize(file_path)
        
        # Создаем метаданные
        metadata = load_metadata()
        file_id = unique_filename
        metadata[file_id] = {
            'original_name': original_filename,
            'unique_name': unique_filename,
            'size': file_size,
            'size_human': format_size(file_size),
            'upload_date': datetime.datetime.now().isoformat(),
            'path': os.path.join(date_subdir, unique_filename),
            'subdir': date_subdir
        }
        
        save_metadata(metadata)
        logger.info(f"Metadata saved for {unique_filename}")
        
        return jsonify({
            'success': True,
            'message': 'File uploaded successfully',
            'file': metadata[file_id]
        }), 200
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        return jsonify({'error': str(e)}), 500

def format_size(size):
    """Форматирует размер файла в человеко-читаемый формат"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"

@app.route('/list')
def list_files():
    """Возвращает список всех файлов с метаданными в JSON"""
    try:
        metadata = load_metadata()
        
        # Сортируем по дате загрузки (новые сверху)
        files_list = list(metadata.values())
        files_list.sort(key=lambda x: x['upload_date'], reverse=True)
        
        return jsonify({
            'total_files': len(files_list),
            'files': files_list
        })
    except Exception as e:
        logger.error(f"List error: {e}")
        return jsonify({'error': str(e)}), 500

def get_files_list():
    """Вспомогательная функция для получения списка файлов для шаблона"""
    try:
        metadata = load_metadata()
        files_list = list(metadata.values())
        files_list.sort(key=lambda x: x['upload_date'], reverse=True)
        return files_list
    except Exception as e:
        logger.error(f"Get files list error: {e}")
        return []

@app.route('/files/<filename>')
def download_file(filename):
    """Скачивает конкретный файл"""
    try:
        metadata = load_metadata()
        
        # Ищем файл по уникальному имени
        if filename in metadata:
            file_info = metadata[filename]
            file_path = os.path.join(STORAGE_DIR, file_info['path'])
            
            if os.path.exists(file_path):
                logger.info(f"Downloading file: {file_path}")
                return send_file(
                    file_path,
                    as_attachment=True,
                    download_name=file_info['original_name']
                )
        
        # Если файл не найден в метаданных, пробуем прямой путь
        for root, dirs, files in os.walk(STORAGE_DIR):
            if filename in files:
                file_path = os.path.join(root, filename)
                logger.info(f"Downloading file (direct): {file_path}")
                return send_file(
                    file_path,
                    as_attachment=True,
                    download_name=filename
                )
        
        return jsonify({'error': 'File not found'}), 404
        
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/delete/<filename>', methods=['DELETE'])
def delete_file(filename):
    """Удаляет файл"""
    try:
        metadata = load_metadata()
        
        if filename in metadata:
            file_info = metadata[filename]
            file_path = os.path.join(STORAGE_DIR, file_info['path'])
            
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"File deleted: {file_path}")
            
            del metadata[filename]
            save_metadata(metadata)
            
            return jsonify({'success': True, 'message': 'File deleted successfully'})
        
        return jsonify({'error': 'File not found'}), 404
        
    except Exception as e:
        logger.error(f"Delete error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/stats')
def stats():
    """Статистика хранилища"""
    try:
        metadata = load_metadata()
        total_size = sum(file['size'] for file in metadata.values())
        
        # Статистика по датам
        stats_by_date = {}
        for file in metadata.values():
            date = file['upload_date'][:10]
            if date not in stats_by_date:
                stats_by_date[date] = {'count': 0, 'total_size': 0}
            stats_by_date[date]['count'] += 1
            stats_by_date[date]['total_size'] += file['size']
        
        return jsonify({
            'total_files': len(metadata),
            'total_size': total_size,
            'total_size_human': format_size(total_size),
            'stats_by_date': stats_by_date
        })
    except Exception as e:
        logger.error(f"Stats error: {e}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Получаем порт из переменной окружения или используем 5000
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)
