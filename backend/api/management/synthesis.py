import json
import logging
import os
import time
import uuid
from django.http import JsonResponse
from azure.identity import DefaultAzureCredential
import requests
import html
import os
import random
import pytz
import datetime
import re
import threading
import traceback
import uuid
import azure.cognitiveservices.speech as speechsdk
from azure.identity import DefaultAzureCredential
from django.http import JsonResponse, HttpResponse, FileResponse
import json
import logging
import time

SPEECH_ENDPOINT = os.getenv('SPEECH_ENDPOINT')
# We recommend to use passwordless authentication with Azure Identity here; meanwhile, you can also use a subscription key instead
PASSWORDLESS_AUTHENTICATION = False
API_VERSION = "2024-04-15-preview"

# Environment variables
# Speech resource (required)
speech_region = os.environ.get('SPEECH_REGION','southeastasia') # e.g. westus2
speech_key = os.environ.get('SPEECH_KEY','31d707b6eb0c4d378753be923f4ce127')
speech_private_endpoint = os.environ.get('SPEECH_PRIVATE_ENDPOINT') # e.g. https://my-speech-service.cognitiveservices.azure.com/ (optional)
speech_resource_url = os.environ.get('SPEECH_RESOURCE_URL','https://southeastasia.api.cognitive.microsoft.com/') # e.g. /subscriptions/6e83d8b7-00dd-4b0a-9e98-dab9f060418b/resourceGroups/my-rg/providers/Microsoft.CognitiveServices/accounts/my-speech (optional, only used for private endpoint)
user_assigned_managed_identity_client_id = os.environ.get('USER_ASSIGNED_MANAGED_IDENTITY_CLIENT_ID') # e.g. the client id of user assigned managed identity accociated to your app service (optional, only used for private endpoint and user assigned managed identity)
# OpenAI resource (required for chat scenario)
azure_openai_endpoint = os.environ.get('AZURE_OPENAI_ENDPOINT','https://openaiedtlab.openai.azure.com/') # e.g. https://my-aoai.openai.azure.com/
azure_openai_api_key = os.environ.get('AZURE_OPENAI_API_KEY','fd789af60ce74928bbe81b49dab6eff8')
azure_openai_deployment_name = os.environ.get('AZURE_OPENAI_DEPLOYMENT_NAME','azurelab') # e.g. my-gpt-35-turbo-deployment
# Cognitive search resource (optional, only required for 'on your data' scenario)
cognitive_search_endpoint = os.environ.get('COGNITIVE_SEARCH_ENDPOINT') # e.g. https://my-cognitive-search.search.windows.net/
cognitive_search_api_key = os.environ.get('COGNITIVE_SEARCH_API_KEY')
cognitive_search_index_name = os.environ.get('COGNITIVE_SEARCH_INDEX_NAME') # e.g. my-search-index
# Customized ICE server (optional, only required for customized ICE server)
ice_server_url = os.environ.get('ICE_SERVER_URL') # The ICE URL, e.g. turn:x.x.x.x:3478
ice_server_url_remote = os.environ.get('ICE_SERVER_URL_REMOTE') # The ICE URL for remote side, e.g. turn:x.x.x.x:3478. This is only required when the ICE address for remote side is different from local side.
ice_server_username = os.environ.get('ICE_SERVER_USERNAME') # The ICE username
ice_server_password = os.environ.get('ICE_SERVER_PASSWORD') # The ICE password

# Const variables
default_tts_voice = 'vi-VN-HoaiMyNeural' # Default TTS voice
sentence_level_punctuations = [ '.', '?', '!', ':', ';', '。', '？', '！', '：', '；' ] # Punctuations that indicate the end of a sentence
enable_quick_reply = False # Enable quick reply for certain chat models which take longer time to respond
quick_replies = [ 'Let me take a look.', 'Let me check.', 'One moment, please.' ] # Quick reply reponses
oyd_doc_regex = re.compile(r'\[doc(\d+)\]') # Regex to match the OYD (on-your-data) document reference

# Global variables
client_contexts = {} # Client contexts
speech_token = None # Speech token
ice_token = None # ICE token


# Initialize the client by creating a client id and an initial context
def initializeClient(client_id=None) -> uuid.UUID:
    if client_id == None:
        client_id = uuid.uuid4()
    client_contexts[client_id] = {
        'azure_openai_deployment_name': azure_openai_deployment_name, # Azure OpenAI deployment name
        'cognitive_search_index_name': cognitive_search_index_name, # Cognitive search index name
        'tts_voice': default_tts_voice, # TTS voice
        'custom_voice_endpoint_id': None, # Endpoint ID (deployment ID) for custom voice
        'personal_voice_speaker_profile_id': None, # Speaker profile ID for personal voice
        'speech_synthesizer': None, # Speech synthesizer for avatar
        'speech_token': None, # Speech token for client side authentication with speech service
        'ice_token': None, # ICE token for ICE/TURN/Relay server connection
        'chat_initiated': False, # Flag to indicate if the chat context is initiated
        'messages': [], # Chat messages (history)
        'data_sources': [], # Data sources for 'on your data' scenario
        'is_speaking': False, # Flag to indicate if the avatar is speaking
        'spoken_text_queue': [], # Queue to store the spoken text
        'speaking_thread': None, # The thread to speak the spoken text queue
        'last_speak_time': None # The last time the avatar spoke
    }
    return client_id

# Refresh the ICE token which being called
def refreshIceToken() -> None:
    global ice_token
    if speech_private_endpoint:
        ice_token = requests.get(f'{speech_private_endpoint}/tts/cognitiveservices/avatar/relay/token/v1', headers={'Ocp-Apim-Subscription-Key': speech_key}).text
    else:
        ice_token = requests.get(f'https://{speech_region}.tts.speech.microsoft.com/cognitiveservices/avatar/relay/token/v1', headers={'Ocp-Apim-Subscription-Key': speech_key}).text

# Refresh the speech token every 9 minutes
def refreshSpeechToken() -> None:
    global speech_token
    while True:
        # Refresh the speech token every 9 minutes
        if speech_private_endpoint:
            credential = DefaultAzureCredential(managed_identity_client_id=user_assigned_managed_identity_client_id)
            token = credential.get_token('https://cognitiveservices.azure.com/.default')
            speech_token = f'aad#{speech_resource_url}#{token.token}'
        else:
            speech_token = requests.post(f'https://{speech_region}.api.cognitive.microsoft.com/sts/v1.0/issueToken', headers={'Ocp-Apim-Subscription-Key': speech_key}).text
        time.sleep(60 * 9)

# Initialize the chat context, e.g. chat history (messages), data sources, etc. For chat scenario.
def initializeChatContext(system_prompt: str, client_id: uuid.UUID) -> None:
    global client_contexts
    client_context = client_contexts[client_id]
    cognitive_search_index_name = client_context['cognitive_search_index_name']
    messages = client_context['messages']
    data_sources = client_context['data_sources']

    # Initialize data sources for 'on your data' scenario
    data_sources.clear()
    if cognitive_search_endpoint and cognitive_search_api_key and cognitive_search_index_name:
        # On-your-data scenario
        data_source = {
            'type': 'AzureCognitiveSearch',
            'parameters': {
                'endpoint': cognitive_search_endpoint,
                'key': cognitive_search_api_key,
                'indexName': cognitive_search_index_name,
                'semanticConfiguration': '',
                'queryType': 'simple',
                'fieldsMapping': {
                    'contentFieldsSeparator': '\n',
                    'contentFields': ['content'],
                    'filepathField': None,
                    'titleField': 'title',
                    'urlField': None
                },
                'inScope': True,
                'roleInformation': system_prompt
            }
        }
        data_sources.append(data_source)

    # Initialize messages
    messages.clear()
    if len(data_sources) == 0:
        system_message = {
            'role': 'system',
            'content': system_prompt
        }
        messages.append(system_message)

def connectAvatar(ClientId,request_body):
    global client_contexts
    client_id = uuid.UUID(ClientId)
    if client_id not in client_contexts:
        initializeClient(client_id)
    client_context = client_contexts[client_id]
    # Override default values with client provided values
    client_context['azure_openai_deployment_name'] = azure_openai_deployment_name
    client_context['cognitive_search_index_name'] = cognitive_search_index_name
    client_context['tts_voice'] = default_tts_voice
    client_context['custom_voice_endpoint_id'] = ''
    client_context['personal_voice_speaker_profile_id'] = ''

    custom_voice_endpoint_id = client_context['custom_voice_endpoint_id']

    try:
        if speech_private_endpoint:
            speech_private_endpoint_wss = speech_private_endpoint.replace('https://', 'wss://')
            speech_config = speechsdk.SpeechConfig(subscription=speech_key, endpoint=f'{speech_private_endpoint_wss}/tts/cognitiveservices/websocket/v1?enableTalkingAvatar=true')
        else:
            speech_config = speechsdk.SpeechConfig(subscription=speech_key, endpoint=f'wss://{speech_region}.tts.speech.microsoft.com/cognitiveservices/websocket/v1?enableTalkingAvatar=true')

        if custom_voice_endpoint_id:
            speech_config.endpoint_id = custom_voice_endpoint_id

        client_context['speech_synthesizer'] = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=None)
        speech_synthesizer = client_context['speech_synthesizer']
        
        ice_token_obj = json.loads(ice_token)
        # Apply customized ICE server if provided
        if ice_server_url and ice_server_username and ice_server_password:
            ice_token_obj = {
                'Urls': [ ice_server_url_remote ] if ice_server_url_remote else [ ice_server_url ],
                'Username': ice_server_username,
                'Password': ice_server_password
            }
        local_sdp = request_body
        avatar_character = 'lisa'
        avatar_style = 'casual-sitting'
        background_color = '#FFFFFFFF'
        background_image_url = None
        is_custom_avatar = 'false'
        transparent_background = 'false'
        video_crop = 'false'
        avatar_config = {
            'synthesis': {
                'video': {
                    'protocol': {
                        'name': "WebRTC",
                        'webrtcConfig': {
                            'clientDescription': local_sdp,
                            'iceServers': [{
                                'urls': [ ice_token_obj['Urls'][0] ],
                                'username': ice_token_obj['Username'],
                                'credential': ice_token_obj['Password']
                            }]
                        },
                    },
                    'format':{
                        'crop':{
                            'topLeft':{
                                'x': 600 if video_crop.lower() == 'true' else 0,
                                'y': 0
                            },
                            'bottomRight':{
                                'x': 1320 if video_crop.lower() == 'true' else 1920,
                                'y': 1080
                            }
                        },
                        'bitrate': 1000000
                    },
                    'talkingAvatar': {
                        'customized': is_custom_avatar.lower() == 'true',
                        'character': avatar_character,
                        'style': avatar_style,
                        'background': {
                            'color': '#00FF00FF' if transparent_background.lower() == 'true' else background_color,
                            'image': {
                                'url': background_image_url
                            }
                        }
                    }
                }
            }
        }
        
        connection = speechsdk.Connection.from_speech_synthesizer(speech_synthesizer)
        connection.set_message_property('speech.config', 'context', json.dumps(avatar_config))

        speech_sythesis_result = speech_synthesizer.speak_text_async('').get()
        print(f'Result id for avatar connection: {speech_sythesis_result.result_id}')
        if speech_sythesis_result.reason == speechsdk.ResultReason.Canceled:
            cancellation_details = speech_sythesis_result.cancellation_details
            print(f"Speech synthesis canceled: {cancellation_details.reason}")
            if cancellation_details.reason == speechsdk.CancellationReason.Error:
                print(f"Error details: {cancellation_details.error_details}")
                raise Exception(cancellation_details.error_details)
        turn_start_message = speech_synthesizer.properties.get_property_by_name('SpeechSDKInternal-ExtraTurnStartMessage')
        remoteSdp = json.loads(turn_start_message)['webrtc']['connectionString']

        return HttpResponse(remoteSdp, status=200)

    except Exception as e:
        return HttpResponse(f"Result ID: {speech_sythesis_result.result_id}. Error message: {e}", status=400)

def getIceToken():
    # Apply customized ICE server if provided
    if ice_server_url and ice_server_username and ice_server_password:
        custom_ice_token = json.dumps({
            'Urls': [ ice_server_url ],
            'Username': ice_server_username,
            'Password': ice_server_password
        })
        return HttpResponse(custom_ice_token, status=200)
    return HttpResponse(ice_token, status=200)

def getSpeechToken():
    global speech_token
    response = HttpResponse(speech_token, status=200)
    response.headers['SpeechRegion'] = speech_region
    if speech_private_endpoint:
        response.headers['SpeechPrivateEndpoint'] = speech_private_endpoint
    return response

def getSpeakingStatus(ClientId):
    global client_contexts
    client_id = uuid.UUID(ClientId)
    is_speaking = client_contexts[client_id]['is_speaking']
    last_speak_time = client_contexts[client_id]['last_speak_time']
    speaking_status = {
        'isSpeaking': is_speaking,
        'lastSpeakTime': last_speak_time.isoformat() if last_speak_time else None
    }
    return HttpResponse(json.dumps(speaking_status), status=200)

# It receives the user query and return the chat response.
# It returns response in stream, which yields the chat response in chunks.
def chat(ClientId,SystemPrompt,user_query):
    global client_contexts
    client_id = uuid.UUID(ClientId)
    client_context = client_contexts[client_id]
    chat_initiated = client_context['chat_initiated']
    if not chat_initiated:
        initializeChatContext(SystemPrompt, client_id)
        client_context['chat_initiated'] = True
    return HttpResponse(handleUserQuery(user_query, client_id), mimetype='text/plain', status=200)

def clearChatHistory(ClientId,SystemPrompt):
    global client_contexts
    client_id = uuid.UUID(ClientId)
    client_context = client_contexts[client_id]
    initializeChatContext(SystemPrompt, client_id)
    client_context['chat_initiated'] = True
    return HttpResponse('Chat history cleared.', status=200)

def disconnectAvatar(ClientId):
    global client_contexts
    client_id = uuid.UUID(ClientId)
    client_context = client_contexts[client_id]
    speech_synthesizer = client_context['speech_synthesizer']
    try:
        connection = speechsdk.Connection.from_speech_synthesizer(speech_synthesizer)
        connection.close()
        return HttpResponse('Disconnected avatar', status=200)
    except:
        return HttpResponse(traceback.format_exc(), status=400)

# Handle the user query and return the assistant reply. For chat scenario.
# The function is a generator, which yields the assistant reply in chunks.
def handleUserQuery(user_query: str, client_id: uuid.UUID):
    global client_contexts
    client_context = client_contexts[client_id]
    azure_openai_deployment_name = client_context['azure_openai_deployment_name']
    messages = client_context['messages']
    data_sources = client_context['data_sources']
    is_speaking = client_context['is_speaking']

    chat_message = {
        'role': 'user',
        'content': user_query
    }

    messages.append(chat_message)

    # Stop previous speaking if there is any
    if is_speaking:
        stopSpeakingInternal(client_id)

    # For 'on your data' scenario, chat API currently has long (4s+) latency
    # We return some quick reply here before the chat API returns to mitigate.
    if len(data_sources) > 0 and enable_quick_reply:
        speakWithQueue(random.choice(quick_replies), 2000, client_id)

    url = f"{azure_openai_endpoint}/openai/deployments/{azure_openai_deployment_name}/chat/completions?api-version=2023-06-01-preview"
    body = json.dumps({
        'messages': messages,
        'stream': True
    })

    if len(data_sources) > 0:
        url = f"{azure_openai_endpoint}/openai/deployments/{azure_openai_deployment_name}/extensions/chat/completions?api-version=2023-06-01-preview"
        body = json.dumps({
            'dataSources': data_sources,
            'messages': messages,
            'stream': True
        })

    assistant_reply = ''
    tool_content = ''
    spoken_sentence = ''

    response = requests.post(url, stream=True, headers={
        'api-key': azure_openai_api_key,
        'Content-Type': 'application/json'
    }, data=body)

    if not response.ok:
        raise Exception(f"Chat API response status: {response.status_code} {response.reason}")

    # Iterate chunks from the response stream
    iterator = response.iter_content(chunk_size=None)
    for chunk in iterator:
        if not chunk:
            # End of stream
            return

        # Process the chunk of data (value)
        chunk_string = chunk.decode()

        if not chunk_string.endswith('}\n\n') and not chunk_string.endswith('[DONE]\n\n'):
            # This is an incomplete chunk, read the next chunk
            while not chunk_string.endswith('}\n\n') and not chunk_string.endswith('[DONE]\n\n'):
                chunk_string += next(iterator).decode()

        for line in chunk_string.split('\n\n'):
            try:
                if line.startswith('data:') and not line.endswith('[DONE]'):
                    response_json = json.loads(line[5:].strip())
                    response_token = None
                    if len(response_json['choices']) > 0:
                        choice = response_json['choices'][0]
                        if len(data_sources) == 0:
                            if len(choice['delta']) > 0 and 'content' in choice['delta']:
                                response_token = choice['delta']['content']
                        elif len(choice['messages']) > 0 and 'delta' in choice['messages'][0]:
                            delta = choice['messages'][0]['delta']
                            if 'role' in delta and delta['role'] == 'tool' and 'content' in delta:
                                tool_content = response_json['choices'][0]['messages'][0]['delta']['content']
                            elif 'content' in delta:
                                response_token = response_json['choices'][0]['messages'][0]['delta']['content']
                                if response_token is not None:
                                    if oyd_doc_regex.search(response_token):
                                        response_token = oyd_doc_regex.sub('', response_token).strip()
                                    if response_token == '[DONE]':
                                        response_token = None

                    if response_token is not None:
                        # Log response_token here if need debug
                        yield response_token # yield response token to client as display text
                        assistant_reply += response_token  # build up the assistant message
                        if response_token == '\n' or response_token == '\n\n':
                            speakWithQueue(spoken_sentence.strip(), 0, client_id)
                            spoken_sentence = ''
                        else:
                            response_token = response_token.replace('\n', '')
                            spoken_sentence += response_token  # build up the spoken sentence
                            if len(response_token) == 1 or len(response_token) == 2:
                                for punctuation in sentence_level_punctuations:
                                    if response_token.startswith(punctuation):
                                        speakWithQueue(spoken_sentence.strip(), 0, client_id)
                                        spoken_sentence = ''
                                        break
            except Exception as e:
                print(f"Error occurred while parsing the response: {e}")
                print(line)

    if spoken_sentence != '':
        speakWithQueue(spoken_sentence.strip(), 0, client_id)
        spoken_sentence = ''

    if len(data_sources) > 0:
        tool_message = {
            'role': 'tool',
            'content': tool_content
        }
        messages.append(tool_message)

    assistant_message = {
        'role': 'assistant',
        'content': assistant_reply
    }
    messages.append(assistant_message)

# Speak the given text. If there is already a speaking in progress, add the text to the queue. For chat scenario.
def speakWithQueue(text: str, ending_silence_ms: int, client_id: uuid.UUID) -> None:
    global client_contexts
    client_context = client_contexts[client_id]
    spoken_text_queue = client_context['spoken_text_queue']
    is_speaking = client_context['is_speaking']
    spoken_text_queue.append(text)
    if not is_speaking:
        def speakThread():
            nonlocal client_context
            nonlocal spoken_text_queue
            nonlocal ending_silence_ms
            tts_voice = client_context['tts_voice']
            personal_voice_speaker_profile_id = client_context['personal_voice_speaker_profile_id']
            client_context['is_speaking'] = True
            while len(spoken_text_queue) > 0:
                text = spoken_text_queue.pop(0)
                speakText(text, tts_voice, personal_voice_speaker_profile_id, ending_silence_ms, client_id)
                client_context['last_speak_time'] = datetime.datetime.now(pytz.UTC)
            client_context['is_speaking'] = False
        client_context['speaking_thread'] = threading.Thread(target=speakThread)
        client_context['speaking_thread'].start()

# Speak the given text.
def speakText(text: str, voice: str, speaker_profile_id: str, ending_silence_ms: int, client_id: uuid.UUID) -> str:
    ssml = f"""<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xmlns:mstts='http://www.w3.org/2001/mstts' xml:lang='en-US'>
                 <voice name='{voice}'>
                     <mstts:ttsembedding speakerProfileId='{speaker_profile_id}'>
                         <mstts:leadingsilence-exact value='0'/>
                         {html.escape(text)}
                     </mstts:ttsembedding>
                 </voice>
               </speak>"""
    if ending_silence_ms > 0:
        ssml = f"""<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xmlns:mstts='http://www.w3.org/2001/mstts' xml:lang='en-US'>
                     <voice name='{voice}'>
                         <mstts:ttsembedding speakerProfileId='{speaker_profile_id}'>
                             <mstts:leadingsilence-exact value='0'/>
                             {html.escape(text)}
                             <break time='{ending_silence_ms}ms' />
                         </mstts:ttsembedding>
                     </voice>
                   </speak>"""
    return speakSsml(ssml, client_id)

# Speak the given ssml with speech sdk
def speakSsml(ssml: str, client_id: uuid.UUID) -> str:
    global client_contexts
    speech_synthesizer = client_contexts[client_id]['speech_synthesizer']
    speech_sythesis_result = speech_synthesizer.speak_ssml_async(ssml).get()
    if speech_sythesis_result.reason == speechsdk.ResultReason.Canceled:
        cancellation_details = speech_sythesis_result.cancellation_details
        print(f"Speech synthesis canceled: {cancellation_details.reason}")
        if cancellation_details.reason == speechsdk.CancellationReason.Error:
            print(f"Result ID: {speech_sythesis_result.result_id}. Error details: {cancellation_details.error_details}")
            raise Exception(cancellation_details.error_details)
    return speech_sythesis_result.result_id

# Stop speaking internal function
def stopSpeakingInternal(client_id: uuid.UUID) -> None:
    global client_contexts
    client_context = client_contexts[client_id]
    speech_synthesizer = client_context['speech_synthesizer']
    spoken_text_queue = client_context['spoken_text_queue']
    spoken_text_queue.clear()
    try:
        connection = speechsdk.Connection.from_speech_synthesizer(speech_synthesizer)
        connection.send_message_async('synthesis.control', '{"action":"stop"}').get()
    except:
        print("Sending message through connection object is not yet supported by current Speech SDK.")

def _authenticate():
    if PASSWORDLESS_AUTHENTICATION:
        # Refer to https://learn.microsoft.com/python/api/overview/azure/identity-readme?view=azure-python#defaultazurecredential
        # for more information about Azure Identity
        # For example, your app can authenticate using your Azure CLI sign-in credentials with when developing locally.
        # Your app can then use a managed identity once it has been deployed to Azure. No code changes are required for this transition.

        # When developing locally, make sure that the user account that is accessing batch avatar synthesis has the right permission.
        # You'll need Cognitive Services User or Cognitive Services Speech User role to submit batch avatar synthesis jobs.
        credential = DefaultAzureCredential()
        token = credential.get_token('https://cognitiveservices.azure.com/.default')
        return {'Authorization': f'Bearer {token.token}'}
    else:
        SUBSCRIPTION_KEY = os.getenv('SUBSCRIPTION_KEY')
        return {'Ocp-Apim-Subscription-Key': SUBSCRIPTION_KEY}

def submit_synthesis(job_id: str, text_content: str):
    url = f'{SPEECH_ENDPOINT}/avatar/batchsyntheses/{job_id}?api-version={API_VERSION}'
    header = {
        'Content-Type': 'application/json'
    }
    header.update(_authenticate())
    isCustomized = False

    payload = {
        'synthesisConfig': {
            "voice": 'vi-VN-HoaiMyNeural',
        },
        # Replace with your custom voice name and deployment ID if you want to use custom voice.
        # Multiple voices are supported, the mixture of custom voices and platform voices is allowed.
        # Invalid voice name or deployment ID will be rejected.
        'customVoices': {
            # "YOUR_CUSTOM_VOICE_NAME": "YOUR_CUSTOM_VOICE_ID"
        },
        "inputKind": "plainText",
        "inputs": [
            {
                "content": text_content,
            },
        ],
        "avatarConfig":
        {
            "customized": isCustomized, # set to True if you want to use customized avatar
            "talkingAvatarCharacter": 'Lisa-technical-sitting',  # talking avatar character
            "videoFormat": "mp4",  # mp4 or webm, webm is required for transparent background
            "videoCodec": "h264",  # hevc, h264 or vp9, vp9 is required for transparent background; default is hevc
            "subtitleType": "soft_embedded",
            "backgroundColor": "#FFFFFFFF", # background color in RGBA format, default is white; can be set to 'transparent' for transparent background
            # "backgroundImage": "https://samples-files.com/samples/Images/jpg/1920-1080-sample.jpg", # background image URL, only support https, either backgroundImage or backgroundColor can be set
        }
        if isCustomized
        else 
        {
            "customized": isCustomized, # set to True if you want to use customized avatar
            "talkingAvatarCharacter": 'Lisa',  # talking avatar character
            "talkingAvatarStyle": 'technical-sitting',  # talking avatar style, required for prebuilt avatar, optional for custom avatar
            "videoFormat": "mp4",  # mp4 or webm, webm is required for transparent background
            "videoCodec": "h264",  # hevc, h264 or vp9, vp9 is required for transparent background; default is hevc
            "subtitleType": "soft_embedded",
            "backgroundColor": "#FFFFFFFF", # background color in RGBA format, default is white; can be set to 'transparent' for transparent background
            # "backgroundImage": "https://samples-files.com/samples/Images/jpg/1920-1080-sample.jpg", # background image URL, only support https, either backgroundImage or backgroundColor can be set
        }
    }

    response = requests.put(url, json.dumps(payload), headers=header)
    if response.status_code < 400:
        logging.info('Batch avatar synthesis job submitted successfully')
        logging.info(f'Job ID: {response.json()["id"]}')
        return True
    else:
        logging.error(f'Failed to submit batch avatar synthesis job: [{response.status_code}], {response.text}')

def list_synthesis_jobs(skip: int = 0, max_page_size: int = 100):
    """List all batch synthesis jobs in the subscription"""
    url = f'{SPEECH_ENDPOINT}/avatar/batchsyntheses?api-version={API_VERSION}&skip={skip}&maxpagesize={max_page_size}'
    header = _authenticate()

    response = requests.get(url, headers=header)
    if response.status_code < 400:
        logging.info(f'List batch synthesis jobs successfully, got {len(response.json()["values"])} jobs')
        logging.info(response.json())
    else:
        logging.error(f'Failed to list batch synthesis jobs: {response.text}')

def generate_synthesis(obj_input):
    # job_id = _create_job_id()
    job_id = obj_input["id"]
    content = obj_input["content"]
    if submit_synthesis(job_id,content):
        response = None
        while True:
            url = f'{SPEECH_ENDPOINT}/avatar/batchsyntheses/{job_id}?api-version={API_VERSION}'
            header = _authenticate()

            response = requests.get(url, headers=header)
            if response.status_code < 400:
                logging.debug('Get batch synthesis job successfully')
                logging.debug(response.json())
                
                status = response.json()['status']
                if status == 'Succeeded':
                    logging.info(f'Batch synthesis job succeeded, download URL: {response.json()["outputs"]["result"]}')
                    logging.info('batch avatar synthesis job succeeded')
                    break
                elif status == 'Failed':
                    logging.error('batch avatar synthesis job failed')
                    break
                else:
                    logging.info(f'batch avatar synthesis job is still running, status [{status}]')
                    time.sleep(5)
            else:
                logging.error(f'Failed to get batch synthesis job: {response.text}')
        
        return JsonResponse(response.json())
