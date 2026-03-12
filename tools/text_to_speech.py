from gtts import gTTS                                                                                                      
import os                                                                                                                  
def text_to_speech(text, lang='es', filename='output/AudioNovelaSintetica.mp3'):                                                                
    tts = gTTS(text=text, lang=lang, slow=False)                                                                           
    tts.save(filename)                                                                                                     
                                                                                                                           
if __name__ == "__main__":                                                                                                 
    with open("NovelaSintetica.txt", "r") as f:
        text = f.read()

    # Reemplazar saltos de línea por espacios para mejorar la fluidez
    formatted_text = text.replace('\n', ' ')
    text_to_speech(formatted_text)
