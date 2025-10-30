import requests
from bs4 import BeautifulSoup
import json
import os
# subprocess ya no se usa directamente para gcloud, pero podría ser útil para otras cosas
import time
import base64
from pydub import AudioSegment
import re
import traceback

# --- Configuración ---
# !!! IMPORTANTE: Reemplaza con la ruta a tu archivo JSON de credenciales !!!
GOOGLE_APPLICATION_CREDENTIALS_FILE = "credenciales.json"
# !!! IMPORTANTE: Reemplaza con el ID de tu proyecto de Google Cloud !!!
GCLOUD_PROJECT_ID = "heroic-bird-459121-h1" # Ej: "heroic-bird-459121-h1"

INPUT_MARKDOWN_FILE = "etica.md"
OUTPUT_DIR = "etica"
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
    1. Elimina espacios extra.
    2. Convierte saltos de línea que no terminan una frase en espacios.
    3. Mantiene saltos de línea que sí terminan frases o separan párrafos.
    """
    if not raw_text:
        return ""

    # Paso 0: Eliminar marcadores de negrita de Markdown
    # Esto reemplaza "**texto en negrita**" con "texto en negrita"
    # y también maneja casos como "***texto***" (que se convertiría en "*texto*")
    # o "****texto****" (que se convertiría en "texto").
    # Para ser más específico y solo quitar los dobles asteriscos:
    text_no_bold_markers = re.sub(r'\*\*(.*?)\*\*', r'\1', raw_text)
    # Si quieres ser más agresivo y quitar cualquier número de asteriscos alrededor de una palabra,
    # podrías usar algo como:
    # text_no_bold_markers = re.sub(r'\*+([^*]+?)\*+', r'\1', raw_text)
    # Pero el primero es más específico para la sintaxis de negrita de Markdown.


    # Paso 1: Normalizar múltiples espacios y limpiar strip inicial/final
    text = re.sub(r'[ \t]+', ' ', raw_text) # Reemplazar múltiples espacios/tabs con uno solo
    text = text.strip()

    # Paso 2: Procesar saltos de línea.
    # Un salto de línea se convierte en espacio SI NO está precedido por [.!?] o por otro \n.
    # Y SI NO está seguido por otro \n (para mantener párrafos separados por líneas en blanco).
    # Usamos un marcador temporal para los \n que queremos conservar.
    placeholder = "##NEWLINE_PLACEHOLDER##"
    
    # Marcar saltos de línea que están al final de una frase o son parte de una separación de párrafo
    # (dos o más \n juntos, o \n precedido por .!?)
    text = re.sub(r'([.!?])\n', rf'\1{placeholder}', text) # . \n -> . placeholder
    text = re.sub(r'\n(\s*\n)+', placeholder, text) # \n\n... -> placeholder

    # Los \n restantes son los que están dentro de frases. Convertirlos a espacio.
    text = text.replace('\n', ' ')

    # Restaurar los saltos de línea marcados.
    text = text.replace(placeholder, '\n')
    
    # Asegurarse de que no haya múltiples espacios de nuevo después de reemplazar \n por ' '
    text = re.sub(r'[ \t]+', ' ', text)
    text = text.strip() # Limpieza final

    # Opcional: Si quieres que la API de TTS haga una pausa más larga en los saltos de párrafo,
    # podrías considerar dejar los párrafos separados por DOS saltos de línea y luego
    # en split_text tratar `\n\n` como el separador de párrafo primario, y `\n` (si queda alguno)
    # como una pausa menor. Pero para el caso actual, un solo `\n` para separar párrafos está bien.

    return text


def parse_markdown_chapters(filepath):
    chapters = []
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: El archivo {filepath} no fue encontrado.")
        return chapters

    chapter_pattern = re.compile(
        r'^\+\+\+\s*title\s*=\s*"(.*?)"\s*weight\s*=\s*\d+\s*\+\+\+$(.*?)(?=(?:^\+\+\+\s*title|\Z))',
        re.MULTILINE | re.DOTALL
    )
    
    matches = list(chapter_pattern.finditer(content))
    if not matches:
        if DEBUG_MODE: print("DEBUG: No se encontraron capítulos con el patrón regex principal. Intentando método alternativo...")
        parts = re.split(r'(\n\s*\+\+\+\s*title\s*=\s*".*?"\s*weight\s*=\s*\d+\s*\+\+\+\s*\n)', content)
        current_title = "Contenido_Inicial_Sin_Titulo_Asignado"
        title_regex_alt = re.compile(r'title\s*=\s*"(.*?)"')

        if parts[0].strip():
            soup = BeautifulSoup(parts[0], 'html.parser')
            raw_chapter_text = soup.get_text(separator='\n', strip=True) # Obtener texto con \n originales
            cleaned_text = clean_chapter_text(raw_chapter_text) # Aplicar limpieza específica
            if cleaned_text:
                 chapters.append((current_title, cleaned_text))
                 if DEBUG_MODE: print(f"DEBUG: Parseado capítulo inicial. Original {len(raw_chapter_text)} chars, Limpio {len(cleaned_text)} chars.")
        
        for i in range(1, len(parts), 2):
            header_part = parts[i]
            content_part = parts[i+1] if (i+1) < len(parts) else ""
            title_match_in_part = title_regex_alt.search(header_part)
            if title_match_in_part:
                current_title = title_match_in_part.group(1).strip()
            else:
                current_title = f"Capitulo_Sin_Titulo_{len(chapters)+1}"
            
            soup = BeautifulSoup(content_part, 'html.parser')
            raw_chapter_text = soup.get_text(separator='\n', strip=True)
            cleaned_text = clean_chapter_text(raw_chapter_text)
            chapters.append((current_title, cleaned_text))
            if DEBUG_MODE: print(f"DEBUG: Parseado capítulo '{current_title}'. Original {len(raw_chapter_text)} chars, Limpio {len(cleaned_text)} chars (método alternativo).")
            
        if chapters and chapters[0][0] == "Contenido_Inicial_Sin_Titulo_Asignado" and not chapters[0][1].strip():
            chapters.pop(0)
    else:
        for match_idx, match in enumerate(matches):
            title = match.group(1).strip()
            chapter_text_html = match.group(2).strip() # HTML del capítulo
            soup = BeautifulSoup(chapter_text_html, 'html.parser')
            raw_chapter_text = soup.get_text(separator='\n', strip=True) # Extraer texto, preservando \n por ahora
            
            if DEBUG_MODE and match_idx < 1: # Solo para el primer capítulo para no inundar logs
                print(f"DEBUG parse_markdown_chapters: Texto crudo (primeros 300 chars) para '{title}':\n'{raw_chapter_text[:300]}'")

            cleaned_text = clean_chapter_text(raw_chapter_text) # Aplicar la nueva limpieza

            if DEBUG_MODE and match_idx < 1:
                print(f"DEBUG parse_markdown_chapters: Texto limpio (primeros 300 chars) para '{title}':\n'{cleaned_text[:300]}'")
            
            chapters.append((title, cleaned_text))
            if DEBUG_MODE: print(f"DEBUG: Parseado capítulo '{title}'. Original {len(raw_chapter_text)} chars, Limpio {len(cleaned_text)} chars (método principal).")
            
    return chapters


def split_text(text, max_length):
    if DEBUG_MODE: print(f"DEBUG split_text: Iniciando división de texto con longitud {len(text)} y max_length {max_length}")
    # Ahora, el texto que llega aquí ya debería tener los \n solo donde realmente son separadores de párrafo.
    # Así que `text.split('\n')` debería funcionar como se espera para obtener párrafos.
    paragraphs_from_input = text.split('\n') 
    chunks = []
    current_chunk_content = ""

    for p_idx, p_text in enumerate(paragraphs_from_input):
        # p_text ya es un párrafo (o una línea si el texto original no tenía muchos \n después de clean_chapter_text)
        # No es necesario p_trimmed = p_text.strip() aquí si clean_chapter_text ya lo hizo,
        # pero no hace daño y asegura que no haya espacios extraños al inicio/final de lo que consideramos un párrafo.
        p_processed = p_text.strip() 

        if DEBUG_MODE and p_idx < 5 : print(f"DEBUG split_text: Procesando párrafo/línea {p_idx}: '{p_processed[:60]}...' (longitud: {len(p_processed)})")

        if not p_processed: # Línea vacía, resultado de dos \n seguidos en el texto limpio.
            if current_chunk_content.strip():
                # Si ya hay contenido, este \n (de p_processed vacío) significa un quiebre de párrafo.
                # Lo añadimos para que el TTS lo interprete.
                current_chunk_content += "\n" 
                if DEBUG_MODE: print(f"DEBUG split_text: Párrafo vacío (línea en blanco) encontrado, añadiendo newline a current_chunk_content (longitud actual: {len(current_chunk_content)})")
            continue

        # Si current_chunk_content ya tiene algo y NO termina en \n (porque el último era un párrafo procesado),
        # y ahora vamos a añadir un nuevo párrafo (p_processed), necesitamos un separador.
        separator = "\n" if current_chunk_content and not current_chunk_content.endswith('\n') else ""
        
        len_if_added = len(current_chunk_content) + len(separator) + len(p_processed)

        if len_if_added <= max_length: # Permitimos que sea igual a max_length
            current_chunk_content += separator + p_processed
            if DEBUG_MODE: print(f"DEBUG split_text: Acumulando párrafo/línea. Longitud de current_chunk_content: {len(current_chunk_content)}")
        else:
            # El párrafo/línea actual (p_processed) hace que el chunk se exceda o lo iguala y no hay espacio para más.
            # Primero, guardar lo que ya teníamos en current_chunk_content (si hay algo)
            if current_chunk_content.strip():
                chunks.append(current_chunk_content.strip())
                if DEBUG_MODE: 
                    log_chunk = current_chunk_content.strip()
                    print(f"DEBUG split_text: Chunk añadido (anterior acumulado). Nuevo chunk de {len(log_chunk)} chars: '{log_chunk[:30]}...{log_chunk[-30:]}'")
            
            # Ahora p_processed es el inicio del nuevo chunk.
            current_chunk_content = p_processed 
            if DEBUG_MODE: print(f"DEBUG split_text: Párrafo/línea actual ('{p_processed[:60]}...') excede. Nuevo current_chunk_content tiene {len(current_chunk_content)} chars.")
            
            # Si este p_processed (que ahora es current_chunk_content) es en sí mismo demasiado largo:
            while len(current_chunk_content) > max_length:
                if DEBUG_MODE: print(f"DEBUG split_text: current_chunk_content ({len(current_chunk_content)} chars) es mayor que max_length ({max_length}). Sub-dividiendo...")
                slice_to_examine = current_chunk_content[:max_length]
                split_point = -1
                found_sep = "NONE"

                # Prioridad de separadores: frases con newline (poco probable aquí si clean_chapter_text funcionó bien),
                # frases con espacio, newline solo (también poco probable), espacio solo.
                # El \n como separador aquí sería si un párrafo individual fuera tan masivo que
                # necesitara dividirse internamente, lo cual es raro para párrafos bien formados.
                # Los separadores primarios serán los de final de frase.
                sentence_enders = ['. ', '! ', '? '] # Prioridad alta
                # Los \n aquí serían si un párrafo individual es ENORME y tiene saltos de línea internos significativos
                # que sobrevivieron a clean_chapter_text (lo cual no debería si no son finales de frase).
                # O si un chunk es solo una frase muy larga sin puntos.
                other_breaks = ['\n'] # Menor prioridad que frases, mayor que espacio simple

                # 1. Buscar finales de frase
                for sep_idx, sep in enumerate(sentence_enders):
                    idx = slice_to_examine.rfind(sep)
                    if idx != -1:
                        # Asegurarse de que el corte no esté demasiado al principio
                        # Si el separador está en los primeros N caracteres, y hay mucho más, podría ser mejor buscar más adelante
                        # o simplemente cortar por espacio. Pero para TTS, cortar en frase es generalmente bueno.
                        split_point = idx + len(sep) # Cortar *después* del separador (incluyendo el espacio)
                        found_sep = sep
                        break
                
                # 2. Si no hay final de frase, buscar otros saltos (como \n si alguno quedó)
                if split_point == -1:
                    for sep_idx, sep in enumerate(other_breaks):
                        idx = slice_to_examine.rfind(sep)
                        if idx != -1:
                            split_point = idx + len(sep) # Cortar después del \n
                            found_sep = sep
                            break
                
                # 3. Si aún no hay, buscar el último espacio
                if split_point == -1: 
                    idx = slice_to_examine.rfind(' ')
                    if idx != -1:
                        split_point = idx + 1 # Cortar después del espacio
                        found_sep = "' '" # Espacio
                    else: # No hay espacios, corte duro (muy improbable en texto narrativo)
                        split_point = max_length
                        found_sep = "max_length_force_cut"
                
                # Evitar bucle infinito si el separador está al inicio y no hay progreso
                if split_point == 0 and max_length > 0 and len(current_chunk_content) > max_length : 
                     split_point = max_length
                     found_sep += " (forced_progress_at_0)"

                chunk_to_add = current_chunk_content[:split_point].strip()

                if DEBUG_MODE: print(f"DEBUG split_text: Sub-división: slice_len={len(slice_to_examine)}, sep_found='{found_sep}', split_point={split_point}")

                if chunk_to_add: 
                    chunks.append(chunk_to_add)
                    if DEBUG_MODE: print(f"DEBUG split_text: Chunk añadido (sub-dividido). Nuevo chunk de {len(chunk_to_add)} chars: '{chunk_to_add[:30]}...{chunk_to_add[-30:]}'")
                
                current_chunk_content = current_chunk_content[split_point:].lstrip() # lstrip() es importante para el progreso
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
    print("--- Iniciando Generador de Audiolibro ---")
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

    print(f"Parseando archivo Markdown: {INPUT_MARKDOWN_FILE}")
    parsed_chapters = parse_markdown_chapters(INPUT_MARKDOWN_FILE)

    if not parsed_chapters:
        print(f"No se pudieron parsear capítulos de {INPUT_MARKDOWN_FILE}. Saliendo.")
        exit(1)

    total_chapters = len(parsed_chapters)
    print(f"Se encontraron {total_chapters} capítulos. (Después de la limpieza de texto)")
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
            
            preview_text = chunk_text.replace('\n', ' <NL> ') # Reemplazar \n con <NL> para verlos en la preview
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

    print("\n--- Proceso Completado ---")
    if all_chapter_final_audio_files:
        print("Archivos de audio de capítulos combinados generados:")
        for f_path in sorted(all_chapter_final_audio_files):
            print(f"  - {os.path.abspath(f_path)}")
    else:
        print("No se generaron archivos de audio de capítulos combinados.")
    print(f"Todos los chunks individuales (si no se borraron) están en subdirectorios dentro de: {os.path.abspath(OUTPUT_DIR)}")
    if DEBUG_MODE: print("MODO DEBUG ESTUVO ACTIVADO.")
    print("--- Fin del Generador de Audiolibro ---")