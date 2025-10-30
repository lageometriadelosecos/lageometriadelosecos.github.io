import requests
from bs4 import BeautifulSoup
import json
import os
import time
import base64
from pydub import AudioSegment
import re
import traceback
import glob

# --- Configuración ---
# !!! IMPORTANTE: Reemplaza con la ruta a tu archivo JSON de credenciales !!!
GOOGLE_APPLICATION_CREDENTIALS_FILE = "content/credenciales.json"
# !!! IMPORTANTE: Reemplaza con el ID de tu proyecto de Google Cloud !!!
GCLOUD_PROJECT_ID = "heroic-bird-459121-h1" # Ej: "heroic-bird-459121-h1"

# Configuración para Libro 1
LIBRO1_DIR = "content/libro1-viernes-interior"
OUTPUT_DIR = "audio_libro1"
MAX_TEXT_CHUNK_SIZE = 4800 

VOICE_CONFIG = {
    "languageCode": "es-ES",
    "name": "es-ES-Chirp3-HD-Fenrir",
}
AUDIO_CONFIG = {
    "audioEncoding": "MP3",
    "sampleRateHertz": 24000
}

REQUEST_TIMEOUT = 90
MAX_SYNTHESIS_RETRIES = 3
RETRY_SLEEP_BASE = 5
INTER_CHUNK_SLEEP = 1.0

DEBUG_MODE = True # Cambia a False para menos verbosidad

# --- Autenticación con Cuenta de Servicio ---
from google.oauth2 import service_account
from google.auth.transport.requests import Request as GoogleAuthRequest

_service_account_token = None
_service_account_token_expiry = 0

def get_access_token_from_service_account():
    global _service_account_token, _service_account_token_expiry
    current_time = time.time()

    if not _service_account_token or current_time >= (_service_account_token_expiry - 120):
        if DEBUG_MODE: print("DEBUG: Obteniendo/Refrescando token de acceso desde cuenta de servicio...")
        try:
            scopes = ['https://www.googleapis.com/auth/cloud-platform']
            credentials = service_account.Credentials.from_service_account_file(
                GOOGLE_APPLICATION_CREDENTIALS_FILE, scopes=scopes)
            
            if not credentials.valid:
                 auth_req = GoogleAuthRequest()
                 credentials.refresh(auth_req)

            _service_account_token = credentials.token
            _service_account_token_expiry = credentials.expiry.timestamp() if credentials.expiry else current_time + 3500 
            if DEBUG_MODE: print(f"DEBUG: Token de cuenta de servicio obtenido/refrescado. Válido hasta: {time.ctime(_service_account_token_expiry)}")
        except Exception as e:
            print(f"Error al obtener/refrescar token de cuenta de servicio: {e}")
            traceback.print_exc()
            _service_account_token = None
            raise
    return _service_account_token

# --- Funciones Auxiliares ---

def sanitize_filename(name):
    name = re.sub(r'[^\w\s.-]', '', name)
    name = re.sub(r'[-\s]+', '_', name).strip('_')
    return name

def clean_chapter_text(raw_text):
    """
    Limpia el texto del capítulo:
    1. Elimina todos los símbolos de markdown.
    2. Elimina espacios extra.
    3. Convierte saltos de línea que no terminan una frase en espacios.
    4. Mantiene saltos de línea que sí terminan frases o separan párrafos.
    """
    if not raw_text:
        return ""

    # Paso 0: Eliminar TODOS los símbolos de markdown
    text = raw_text
    
    # Eliminar negritas (**texto** o __texto__)
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)
    
    # Eliminar cursivas (*texto* o _texto_)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)
    
    # Eliminar tachado (~~texto~~)
    text = re.sub(r'~~(.*?)~~', r'\1', text)
    
    # Eliminar código en línea (`texto`)
    text = re.sub(r'`(.*?)`', r'\1', text)
    
    # Eliminar enlaces [texto](url)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    
    # Eliminar imágenes ![alt](url)
    text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', text)
    
    # Eliminar headers (# ## ### etc.)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    
    # Eliminar listas (- * +)
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)
    
    # Eliminar listas numeradas (1. 2. etc.)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    
    # Eliminar bloques de código (``` o ~~~)
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'~~~.*?~~~', '', text, flags=re.DOTALL)
    
    # Eliminar referencias de markdown [^1] [^nota]
    text = re.sub(r'\[\^[^\]]+\]', '', text)
    
    # Eliminar separadores horizontales (--- o ***)
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    
    # Eliminar tablas (| separadores)
    text = re.sub(r'^\s*\|.*\|.*$', '', text, flags=re.MULTILINE)
    
    # Eliminar citas (> texto)
    text = re.sub(r'^\s*>\s*', '', text, flags=re.MULTILINE)
    
    # Eliminar asteriscos específicamente (más agresivo)
    text = re.sub(r'\*+', '', text)
    
    # Eliminar otros caracteres especiales de markdown que puedan quedar
    text = re.sub(r'[\\`_{}[\]()#+\-.!]', '', text)
    
    # Eliminar guiones múltiples
    text = re.sub(r'-+', '-', text)
    
    # Eliminar guiones al inicio de líneas
    text = re.sub(r'^\s*-+\s*', '', text, flags=re.MULTILINE)
    
    # Limpieza final agresiva de asteriscos y otros símbolos problemáticos
    text = re.sub(r'\*', '', text)  # Eliminar cualquier asterisco que quede
    text = re.sub(r'[^\w\s.,;:!?¿¡\-\'\"()]', ' ', text)  # Solo mantener letras, números, espacios y puntuación básica

    # Paso 1: Normalizar múltiples espacios y limpiar strip inicial/final
    text = re.sub(r'[ \t]+', ' ', text) # Reemplazar múltiples espacios/tabs con uno solo
    text = text.strip()

    # Paso 2: Procesar saltos de línea.
    placeholder = "##NEWLINE_PLACEHOLDER##"
    
    # Marcar saltos de línea que están al final de una frase o son parte de una separación de párrafo
    text = re.sub(r'([.!?])\n', rf'\1{placeholder}', text) # . \n -> . placeholder
    text = re.sub(r'\n(\s*\n)+', placeholder, text) # \n\n... -> placeholder

    # Los \n restantes son los que están dentro de frases. Convertirlos a espacio.
    text = text.replace('\n', ' ')

    # Restaurar los saltos de línea marcados.
    text = text.replace(placeholder, '\n')
    
    # Asegurarse de que no haya múltiples espacios de nuevo después de reemplazar \n por ' '
    text = re.sub(r'[ \t]+', ' ', text)
    text = text.strip() # Limpieza final

    # Debug: Mostrar muestra del texto limpio si está en modo debug
    if DEBUG_MODE and text:
        sample_text = text[:200] + "..." if len(text) > 200 else text
        print(f"DEBUG clean_chapter_text: Muestra del texto limpio: '{sample_text}'")
        # Verificar si aún hay asteriscos
        if '*' in text:
            asterisk_positions = [i for i, char in enumerate(text) if char == '*']
            print(f"DEBUG clean_chapter_text: ADVERTENCIA: Aún hay asteriscos en posiciones: {asterisk_positions[:10]}")

    return text

def parse_markdown_chapter(filepath):
    """
    Parsea un capítulo individual de markdown y extrae su contenido
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: El archivo {filepath} no fue encontrado.")
        return None, ""

    # Extraer el título del archivo si tiene front matter
    title = os.path.basename(filepath).replace('.md', '')
    
    # Buscar front matter
    front_matter_pattern = re.compile(r'^\+\+\+\s*(.*?)\s*\+\+\+', re.DOTALL)
    front_matter_match = front_matter_pattern.match(content)
    
    if front_matter_match:
        front_matter = front_matter_match.group(1)
        # Extraer título del front matter si existe
        title_match = re.search(r'title\s*=\s*["\'](.*?)["\']', front_matter)
        if title_match:
            title = title_match.group(1)
        # Remover front matter del contenido
        content = content[front_matter_match.end():]

    # Procesar el contenido HTML si existe
    soup = BeautifulSoup(content, 'html.parser')
    raw_chapter_text = soup.get_text(separator='\n', strip=True)
    cleaned_text = clean_chapter_text(raw_chapter_text)
    
    return title, cleaned_text

def get_libro1_chapters():
    """
    Obtiene todos los capítulos del Libro 1, excluyendo el index.md
    """
    chapters = []
    
    if not os.path.exists(LIBRO1_DIR):
        print(f"Error: El directorio {LIBRO1_DIR} no existe.")
        return chapters
    
    # Buscar todos los archivos .md excepto index.md
    md_files = glob.glob(os.path.join(LIBRO1_DIR, "*.md"))
    md_files = [f for f in md_files if not f.endswith('index.md')]
    
    # Ordenar por nombre para mantener el orden de los capítulos
    md_files.sort()
    
    for md_file in md_files:
        title, content = parse_markdown_chapter(md_file)
        if content.strip():
            chapters.append((title, content))
            if DEBUG_MODE: print(f"DEBUG: Capítulo cargado '{title}' - {len(content)} caracteres")
    
    return chapters

def split_long_sentences(text, max_sentence_length=500):
    """
    Divide oraciones extremadamente largas que pueden causar problemas en TTS
    """
    if not text:
        return text
    
    # Buscar oraciones que terminen con puntuación
    sentences = re.split(r'([.!?]+\s+)', text)
    result_sentences = []
    
    for i in range(0, len(sentences), 2):
        if i < len(sentences):
            sentence = sentences[i]
            punctuation = sentences[i+1] if i+1 < len(sentences) else ""
            
            if len(sentence) > max_sentence_length:
                # Dividir oración larga por comas, puntos y comas, o dos puntos
                sub_sentences = re.split(r'([,;:]+\s+)', sentence)
                temp_sentence = ""
                
                for j in range(0, len(sub_sentences), 2):
                    if j < len(sub_sentences):
                        part = sub_sentences[j]
                        separator = sub_sentences[j+1] if j+1 < len(sub_sentences) else ""
                        
                        if len(temp_sentence + part) > max_sentence_length and temp_sentence:
                            result_sentences.append(temp_sentence + ".")
                            temp_sentence = part + separator
                        else:
                            temp_sentence += part + separator
                
                if temp_sentence:
                    result_sentences.append(temp_sentence + punctuation)
            else:
                result_sentences.append(sentence + punctuation)
    
    return ' '.join(result_sentences)

def split_text(text, max_length):
    if DEBUG_MODE: print(f"DEBUG split_text: Iniciando división de texto con longitud {len(text)} y max_length {max_length}")
    
    # Primero dividir oraciones extremadamente largas
    text = split_long_sentences(text, max_sentence_length=500)
    
    paragraphs_from_input = text.split('\n') 
    chunks = []
    current_chunk_content = ""

    for p_idx, p_text in enumerate(paragraphs_from_input):
        p_processed = p_text.strip() 

        if DEBUG_MODE and p_idx < 5 : print(f"DEBUG split_text: Procesando párrafo/línea {p_idx}: '{p_processed[:60]}...' (longitud: {len(p_processed)})")

        if not p_processed: # Línea vacía
            if current_chunk_content.strip():
                current_chunk_content += "\n" 
                if DEBUG_MODE: print(f"DEBUG split_text: Párrafo vacío encontrado, añadiendo newline a current_chunk_content (longitud actual: {len(current_chunk_content)})")
            continue

        separator = "\n" if current_chunk_content and not current_chunk_content.endswith('\n') else ""
        len_if_added = len(current_chunk_content) + len(separator) + len(p_processed)

        if len_if_added <= max_length:
            current_chunk_content += separator + p_processed
            if DEBUG_MODE: print(f"DEBUG split_text: Acumulando párrafo/línea. Longitud de current_chunk_content: {len(current_chunk_content)}")
        else:
            if current_chunk_content.strip():
                chunks.append(current_chunk_content.strip())
                if DEBUG_MODE: 
                    log_chunk = current_chunk_content.strip()
                    print(f"DEBUG split_text: Chunk añadido (anterior acumulado). Nuevo chunk de {len(log_chunk)} chars: '{log_chunk[:30]}...{log_chunk[-30:]}'")
            
            current_chunk_content = p_processed 
            if DEBUG_MODE: print(f"DEBUG split_text: Párrafo/línea actual ('{p_processed[:60]}...') excede. Nuevo current_chunk_content tiene {len(current_chunk_content)} chars.")
            
            # Si este párrafo es demasiado largo, subdividirlo
            while len(current_chunk_content) > max_length:
                if DEBUG_MODE: print(f"DEBUG split_text: current_chunk_content ({len(current_chunk_content)} chars) es mayor que max_length ({max_length}). Sub-dividiendo...")
                slice_to_examine = current_chunk_content[:max_length]
                split_point = -1
                found_sep = "NONE"

                # Prioridad 1: Buscar finales de frase con puntuación
                sentence_enders = ['. ', '! ', '? ', '; ', ': ']
                for sep_idx, sep in enumerate(sentence_enders):
                    idx = slice_to_examine.rfind(sep)
                    if idx != -1 and idx > max_length * 0.3:  # No cortar muy al principio
                        split_point = idx + len(sep)
                        found_sep = sep
                        break
                
                # Prioridad 2: Buscar comas (para oraciones muy largas)
                if split_point == -1:
                    comma_idx = slice_to_examine.rfind(', ')
                    if comma_idx != -1 and comma_idx > max_length * 0.4:
                        split_point = comma_idx + len(', ')
                        found_sep = ", "
                
                # Prioridad 3: Buscar otros saltos
                if split_point == -1:
                    other_breaks = ['\n', ' - ', ' — ', ' – ']
                    for sep_idx, sep in enumerate(other_breaks):
                        idx = slice_to_examine.rfind(sep)
                        if idx != -1 and idx > max_length * 0.3:
                            split_point = idx + len(sep)
                            found_sep = sep
                            break
                
                # Prioridad 4: Buscar el último espacio (como último recurso)
                if split_point == -1: 
                    idx = slice_to_examine.rfind(' ')
                    if idx != -1 and idx > max_length * 0.5:  # No cortar muy al principio
                        split_point = idx + 1
                        found_sep = "' '"
                    else: # No hay espacios, corte duro
                        split_point = max_length
                        found_sep = "max_length_force_cut"
                
                # Evitar bucle infinito
                if split_point == 0 and max_length > 0 and len(current_chunk_content) > max_length : 
                     split_point = max_length
                     found_sep += " (forced_progress_at_0)"

                chunk_to_add = current_chunk_content[:split_point].strip()

                if DEBUG_MODE: print(f"DEBUG split_text: Sub-división: slice_len={len(slice_to_examine)}, sep_found='{found_sep}', split_point={split_point}")

                if chunk_to_add: 
                    chunks.append(chunk_to_add)
                    if DEBUG_MODE: print(f"DEBUG split_text: Chunk añadido (sub-dividido). Nuevo chunk de {len(chunk_to_add)} chars: '{chunk_to_add[:30]}...{chunk_to_add[-30:]}'")
                
                current_chunk_content = current_chunk_content[split_point:].lstrip()
                if DEBUG_MODE: print(f"DEBUG split_text: Remanente de current_chunk_content: {len(current_chunk_content)} chars: '{current_chunk_content[:30]}...'")
    
    # Añadir el último chunk restante
    if current_chunk_content.strip():
        final_chunk_to_add = current_chunk_content.strip()
        chunks.append(final_chunk_to_add)
        if DEBUG_MODE: print(f"DEBUG split_text: Chunk final añadido. Chunk de {len(final_chunk_to_add)} chars: '{final_chunk_to_add[:30]}...{final_chunk_to_add[-30:]}'")
    
    if DEBUG_MODE: print(f"DEBUG split_text: División completada. Total de chunks generados: {len(chunks)}")
    return chunks

def synthesize_text_chunk(text_chunk, project_id, access_token_provider_func, chunk_idx_for_log="N/A"):
    tts_url = "https://texttospeech.googleapis.com/v1/text:synthesize"
    
    for attempt in range(MAX_SYNTHESIS_RETRIES):
        if DEBUG_MODE: print(f"DEBUG synthesize: Chunk {chunk_idx_for_log}, Intento {attempt+1}/{MAX_SYNTHESIS_RETRIES}")
        try:
            current_token = access_token_provider_func() 
            if not current_token:
                print(f"Intento {attempt+1} (Chunk {chunk_idx_for_log}): No se pudo obtener token. Saltando.")
                return None

            headers = {
                "Content-Type": "application/json",
                "X-Goog-User-Project": project_id,
                "Authorization": f"Bearer {current_token}"
            }
            input_data = {"text": text_chunk}
            data = {
                "input": input_data,
                "voice": VOICE_CONFIG,
                "audioConfig": AUDIO_CONFIG
            }

            response = requests.post(tts_url, headers=headers, data=json.dumps(data), timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            
            response_json = response.json()
            if "audioContent" in response_json:
                if DEBUG_MODE: print(f"DEBUG synthesize: Chunk {chunk_idx_for_log}, Síntesis exitosa en intento {attempt+1}.")
                return base64.b64decode(response_json["audioContent"])
            else:
                print(f"Intento {attempt+1} (Chunk {chunk_idx_for_log}): Respuesta API sin 'audioContent'. Detalles: {response_json}")
                return None

        except requests.exceptions.HTTPError as http_err:
            error_message = f"Intento {attempt+1} (Chunk {chunk_idx_for_log}): Error HTTP "
            response_text_content = "No se pudo obtener el cuerpo de la respuesta."
            
            if http_err.response is not None:
                error_message += f"{http_err.response.status_code} "
                try:
                    response_text_content = json.dumps(http_err.response.json(), indent=2)
                except json.JSONDecodeError:
                    response_text_content = http_err.response.text 
            else:
                 error_message += "N/A "
            
            error_message += f"en API TTS: {http_err}"
            print(error_message)
            print(f"CUERPO RESPUESTA ERROR (Chunk {chunk_idx_for_log}):\n{response_text_content}\n")
            
            should_retry = False
            if http_err.response is not None and http_err.response.status_code in [401, 403, 429, 500, 502, 503, 504]:
                should_retry = True
            
            if "INVALID_ARGUMENT" in response_text_content and "Input text not set" in response_text_content:
                print(f"Error específico (Chunk {chunk_idx_for_log}): 'Input text not set'. Posible chunk vacío o problemático.")
                print(f"Texto del chunk (primeros/últimos 50 chars): '{text_chunk[:50]}...{text_chunk[-50:]}'")
                return None 

            if "INVALID_ARGUMENT" in response_text_content and "input.text" in response_text_content and "exceeds limit" in response_text_content:
                print(f"Error específico (Chunk {chunk_idx_for_log}): El chunk excede límite API (5000 bytes). Longitud texto: {len(text_chunk)} chars.")
                print(f"Texto del chunk (primeros 100 chars): {text_chunk[:100]}")
                return None

            if should_retry and attempt < MAX_SYNTHESIS_RETRIES - 1:
                wait_time = RETRY_SLEEP_BASE * (2 ** attempt) 
                print(f"Reintentando Chunk {chunk_idx_for_log} en {wait_time} segundos...")
                time.sleep(wait_time)
            elif not should_retry:
                 print(f"Error no recuperable para Chunk {chunk_idx_for_log}, no se reintentará.")
                 return None
            else:
                 print(f"Se agotaron los reintentos para Chunk {chunk_idx_for_log}.")
                 return None
            
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as conn_err:
            print(f"Intento {attempt+1} (Chunk {chunk_idx_for_log}): Error de conexión/timeout API TTS: {conn_err}")
            if attempt < MAX_SYNTHESIS_RETRIES - 1:
                wait_time = RETRY_SLEEP_BASE * (2 ** attempt)
                print(f"Reintentando Chunk {chunk_idx_for_log} en {wait_time} segundos...")
                time.sleep(wait_time)
            else:
                return None

        except Exception as e:
            print(f"Intento {attempt+1} (Chunk {chunk_idx_for_log}): Error inesperado durante síntesis: {e}")
            print(f"Texto del chunk problemático (primeros 100 chars): {text_chunk[:100]}")
            traceback.print_exc()
            return None 

    print(f"Todos los {MAX_SYNTHESIS_RETRIES} intentos de síntesis fallaron para el fragmento {chunk_idx_for_log}.")
    return None

# --- Flujo Principal ---
if __name__ == "__main__":
    print("--- Iniciando Generador de Audiolibro - Libro 1: El Viernes Interior ---")
    if DEBUG_MODE: print("MODO DEBUG ACTIVADO: Se mostrará información detallada.")

    if not os.path.exists(GOOGLE_APPLICATION_CREDENTIALS_FILE):
        print(f"Error Crítico: Archivo de credenciales JSON no encontrado: {GOOGLE_APPLICATION_CREDENTIALS_FILE}")
        exit(1)
    if GCLOUD_PROJECT_ID == "tu-gcloud-project-id" or not GCLOUD_PROJECT_ID :
        print(f"Error Crítico: Debes configurar tu GCLOUD_PROJECT_ID en el script.")
        exit(1)

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
        print(f"Directorio de salida creado: {os.path.abspath(OUTPUT_DIR)}")

    try:
        print("Verificando autenticación inicial con cuenta de servicio...")
        get_access_token_from_service_account() 
        print(f"Autenticación con cuenta de servicio OK para proyecto: {GCLOUD_PROJECT_ID}")
    except Exception as e:
        print(f"Error Crítico en configuración inicial con credenciales: {e}")
        exit(1)

    print(f"Cargando capítulos del Libro 1 desde: {LIBRO1_DIR}")
    parsed_chapters = get_libro1_chapters()

    if not parsed_chapters:
        print(f"No se pudieron cargar capítulos del {LIBRO1_DIR}. Saliendo.")
        exit(1)

    total_chapters = len(parsed_chapters)
    print(f"Se encontraron {total_chapters} capítulos del Libro 1. (Después de la limpieza de texto)")
    all_chapter_final_audio_files = []

    for i, (chapter_title, chapter_content) in enumerate(parsed_chapters):
        chapter_num_log = f"({i+1}/{total_chapters})"
        original_chapter_title_for_log = chapter_title if chapter_title else f"Capitulo_Indice_{i+1}"
        sanitized_chapter_title = sanitize_filename(original_chapter_title_for_log)
        chapter_output_dir = os.path.join(OUTPUT_DIR, sanitized_chapter_title)
        
        audio_ext = AUDIO_CONFIG["audioEncoding"].lower()
        if audio_ext == "linear16": audio_ext = "wav"
        elif audio_ext == "ogg_opus": audio_ext = "ogg"
        
        final_chapter_audio_path = os.path.join(OUTPUT_DIR, f"{i:02d}_{sanitized_chapter_title}.{audio_ext}")

        print(f"\n--- Procesando Capítulo {chapter_num_log}: {original_chapter_title_for_log} ---")
        if DEBUG_MODE: 
            print(f"DEBUG: Longitud del contenido del capítulo (después de clean_chapter_text): {len(chapter_content)} caracteres.")
            print(f"DEBUG: Ruta final esperada para el capítulo: {final_chapter_audio_path}")

        if os.path.exists(final_chapter_audio_path) and os.path.getsize(final_chapter_audio_path) > 100: 
            print(f"  INFO: Archivo combinado del capítulo '{original_chapter_title_for_log}' ya existe. Omitiendo: {final_chapter_audio_path}")
            all_chapter_final_audio_files.append(final_chapter_audio_path)
            continue

        if not os.path.exists(chapter_output_dir):
            os.makedirs(chapter_output_dir)
            if DEBUG_MODE: print(f"DEBUG: Directorio de chunks para capítulo creado: {chapter_output_dir}")

        if not chapter_content.strip():
            print(f"  ADVERTENCIA: Contenido vacío para capítulo '{original_chapter_title_for_log}'. Omitiendo.")
            continue

        print(f"  Dividiendo texto del capítulo en fragmentos (max_size={MAX_TEXT_CHUNK_SIZE} chars)...")
        text_chunks = split_text(chapter_content, MAX_TEXT_CHUNK_SIZE)
        total_chunks_for_chapter = len(text_chunks)
        print(f"  Texto dividido en {total_chunks_for_chapter} fragmentos.")

        chapter_chunk_audio_files = []
        for j, chunk_text in enumerate(text_chunks):
            chunk_num_log = f"({j+1}/{total_chunks_for_chapter})"
            print(f"  Procesando fragmento {chunk_num_log} para '{original_chapter_title_for_log}' (longitud: {len(chunk_text)} chars)...")
            
            preview_text = chunk_text.replace('\n', ' <NL> ')
            max_preview_len = 70
            if len(preview_text) > max_preview_len:
                preview_display = f"'{preview_text[:max_preview_len//2]}...{preview_text[-(max_preview_len//2):]}'"
            else:
                preview_display = f"'{preview_text}'"
            print(f"    Texto del fragmento: {preview_display}")

            if not chunk_text.strip():
                print(f"    ADVERTENCIA: Fragmento {chunk_num_log} está vacío después de strip. Omitiendo.")
                continue
            
            chunk_file_name = f"chunk_{j:03d}.{audio_ext}"
            chunk_file_path = os.path.join(chapter_output_dir, chunk_file_name)
            if DEBUG_MODE: print(f"DEBUG: Ruta esperada para el fragmento de audio: {chunk_file_path}")

            if os.path.exists(chunk_file_path) and os.path.getsize(chunk_file_path) > 100: 
                print(f"    INFO: Fragmento '{chunk_file_name}' ya existe. Omitiendo síntesis.")
            else:
                print(f"    Sintetizando audio para fragmento {chunk_num_log}...")
                audio_data = synthesize_text_chunk(chunk_text, GCLOUD_PROJECT_ID, get_access_token_from_service_account, chunk_idx_for_log=f"{original_chapter_title_for_log} - Chunk {j+1}")
                if audio_data:
                    with open(chunk_file_path, "wb") as f:
                        f.write(audio_data)
                    print(f"    ÉXITO: Fragmento guardado en: {chunk_file_path}")
                else:
                    print(f"    FALLO: No se pudo sintetizar el fragmento {chunk_num_log}.")
                    failed_chunk_text_file = os.path.join(chapter_output_dir, f"failed_chunk_{j:03d}.txt")
                    try:
                        with open(failed_chunk_text_file, "w", encoding="utf-8") as f_err:
                            f_err.write(chunk_text)
                        print(f"    INFO: Texto del fragmento fallido guardado en: {failed_chunk_text_file}")
                    except Exception as e_write:
                        print(f"    ERROR: No se pudo guardar el texto del fragmento fallido: {e_write}")
                    continue 
            
            chapter_chunk_audio_files.append(chunk_file_path)
            if DEBUG_MODE and j < total_chunks_for_chapter -1: print(f"DEBUG: Pausa de {INTER_CHUNK_SLEEP}s antes del siguiente fragmento.")
            time.sleep(INTER_CHUNK_SLEEP)

        if chapter_chunk_audio_files:
            print(f"  Combinando {len(chapter_chunk_audio_files)} fragmentos de audio para '{original_chapter_title_for_log}'...")
            valid_chunk_files = [f for f in chapter_chunk_audio_files if os.path.exists(f) and os.path.getsize(f) > 100]
            
            if not valid_chunk_files:
                print(f"    ADVERTENCIA: No hay fragmentos de audio válidos para combinar para '{original_chapter_title_for_log}'.")
                continue

            combined_audio = AudioSegment.empty()
            for audio_idx, audio_file_path in enumerate(valid_chunk_files):
                if DEBUG_MODE: print(f"DEBUG combine: Añadiendo '{os.path.basename(audio_file_path)}' al audio combinado del capítulo.")
                try:
                    segment = AudioSegment.from_file(audio_file_path, format=audio_ext)
                    combined_audio += segment
                except Exception as e:
                    print(f"    ERROR al cargar/combinar {audio_file_path}: {e}. Omitiendo este fragmento en la combinación.")
            
            if len(combined_audio) > 0:
                try:
                    print(f"    Exportando audio combinado a: {final_chapter_audio_path}")
                    combined_audio.export(final_chapter_audio_path, format=audio_ext)
                    print(f"  ÉXITO: Capítulo '{original_chapter_title_for_log}' guardado en: {final_chapter_audio_path}")
                    all_chapter_final_audio_files.append(final_chapter_audio_path)
                except Exception as e:
                    print(f"    ERROR al exportar audio combinado para '{original_chapter_title_for_log}': {e}")
                    traceback.print_exc()
            else:
                print(f"    ADVERTENCIA: No se pudo generar audio combinado para '{original_chapter_title_for_log}' (audio combinado vacío).")
        else:
            print(f"  INFO: No se generaron fragmentos de audio para '{original_chapter_title_for_log}'.")

    print("\n--- Proceso Completado - Libro 1: El Viernes Interior ---")
    if all_chapter_final_audio_files:
        print("Archivos de audio de capítulos combinados generados:")
        for f_path in sorted(all_chapter_final_audio_files):
            print(f"  - {os.path.abspath(f_path)}")
        
        # Crear un archivo de audio combinado de todo el libro
        print(f"\nCombinando todos los capítulos en un audiolibro completo...")
        libro_completo_path = os.path.join(OUTPUT_DIR, "Libro1_El_Viernes_Interior_Completo.mp3")
        
        if os.path.exists(libro_completo_path) and os.path.getsize(libro_completo_path) > 100:
            print(f"  INFO: Audiolibro completo ya existe. Omitiendo: {libro_completo_path}")
        else:
            try:
                libro_completo_audio = AudioSegment.empty()
                for audio_file in sorted(all_chapter_final_audio_files):
                    if DEBUG_MODE: print(f"DEBUG: Añadiendo '{os.path.basename(audio_file)}' al audiolibro completo.")
                    segment = AudioSegment.from_file(audio_file, format=audio_ext)
                    libro_completo_audio += segment
                    # Añadir una pausa de 2 segundos entre capítulos
                    libro_completo_audio += AudioSegment.silent(duration=2000)
                
                libro_completo_audio.export(libro_completo_path, format="mp3")
                print(f"  ÉXITO: Audiolibro completo guardado en: {libro_completo_path}")
            except Exception as e:
                print(f"  ERROR al crear audiolibro completo: {e}")
                traceback.print_exc()
    else:
        print("No se generaron archivos de audio de capítulos combinados.")
    print(f"Todos los chunks individuales (si no se borraron) están en subdirectorios dentro de: {os.path.abspath(OUTPUT_DIR)}")
    if DEBUG_MODE: print("MODO DEBUG ESTUVO ACTIVADO.")
    print("--- Fin del Generador de Audiolibro - Libro 1 ---")
