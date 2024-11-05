import uuid
from azure.identity import DefaultAzureCredential
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.http import JsonResponse, HttpResponse, FileResponse
import json
import logging
import threading
from .management import conversation_client,sample_user,synthesis,chatgpt, auth_utils
from django.middleware.csrf import get_token
import time
# from django.views.decorators.csrf import csrf_exempt

@require_POST
def genate_avatar(request):
    request_body = json.loads(request.body)
    try:
        return synthesis.generate_synthesis(request_body)
    except Exception as e:
        logging.exception("Exception in /conversation")
        return JsonResponse({"error": str(e)}, status=500)

@require_POST
def conversation(request):
    try:
        request_body = json.loads(request.body)
        # return chatgpt.conversation_internal(request_body,request)
        return chatgpt.conversation_groq(request_body)
    except Exception as e:
        logging.exception("Exception in /conversation")
        return JsonResponse({"error": str(e)}, status=500)

@require_GET
def auth_me(request):
    try:
        user_object = auth_utils.get_authenticated_user_details(request.headers)
        return JsonResponse(user_object, status=200)
    except Exception as e:
        logging.exception("Exception in /conversation")
        return JsonResponse({"error": str(e)}, status=401)

@require_GET
def ensure_db(request):   
    if not conversation_client.ensure():
        return JsonResponse({"error": "DBs is not working"})

    return JsonResponse({"message": "DB is configured and working"})

@require_POST
def add_conversation(request):
    request_body = json.loads(request.body)
    authenticated_user = auth_utils.get_authenticated_user_details(request.headers)
    user_id = authenticated_user['user_principal_id']

    ## check request for conversation_id
    conversation_id = request_body.get("conversation_id", None)

    try:
        # check for the conversation_id, if the conversation is not set, we will create a new one
        history_metadata = {}
        if not conversation_id:
            # title = chatgpt.generate_title(request_body["messages"])
            title = chatgpt.generate_title_groq(request_body["messages"])
            conversation_dict = conversation_client.create_conversation(user_id=user_id, title=title)
            conversation_id = str(conversation_dict.id)
            history_metadata['title'] = title
            history_metadata['date'] = conversation_dict.created_at.isoformat()
            
        ## Format the incoming message object in the "chat/completions" messages format
        ## then write it to the conversation history in cosmos
        messages = request_body["messages"]
        if len(messages) > 0 and messages[-1]['role'] == "user":
            conversation_client.create_message(
                conversation_id=conversation_id,
                user_id=user_id,
                input_message=messages[-1]
            )
        else:
            raise Exception("No user message found")
        
        # Submit request to Chat Completions for response
        history_metadata['conversation_id'] = conversation_id
        request_body['history_metadata'] = history_metadata
        return chatgpt.conversation_internal(request_body,request)
       
    except Exception as e:
        logging.exception("Exception in /history/generate")
        return JsonResponse({"error": str(e)}, status=500)

@require_POST
def update_conversation(request):
    request_body = json.loads(request.body)
    authenticated_user = auth_utils.get_authenticated_user_details(request.headers)
    user_id = authenticated_user['user_principal_id']

    ## check request for conversation_id
    conversation_id = request_body.get("conversation_id", None)

    try:
        # check for the conversation_id, if the conversation is not set, we will create a new one
        if not conversation_id:
            raise Exception("No conversation_id found")
            
        ## Format the incoming message object in the "chat/completions" messages format
        ## then write it to the conversation history in cosmos
        messages = request_body["messages"]
        if len(messages) > 0 and messages[-1]['role'] == "assistant":
            if len(messages) > 1 and messages[-2] != {} and messages[-2]['role'] == "tool":
                # write the tool message first
                conversation_client.create_message(
                    conversation_id=conversation_id,
                    user_id=user_id,
                    input_message=messages[-2]
                )
            # write the assistant message
            conversation_client.create_message(
                conversation_id=conversation_id,
                user_id=user_id,
                input_message=messages[-1]
            )
        else:
            raise Exception("No bot messages found")
        
        # Submit request to Chat Completions for response
        response = {'success': True}
        return JsonResponse(response, status=200)
       
    except Exception as e:
        logging.exception("Exception in /history/update")
        return JsonResponse({"error": str(e)}, status=500)

@require_http_methods(["DELETE"])
def delete_conversation(request):
    request_body = json.loads(request.body)
    ## get the user id from the request headers
    authenticated_user = auth_utils.get_authenticated_user_details(request.headers)
    user_id = authenticated_user['user_principal_id']
    
    ## check request for conversation_id
    conversation_id = request_body.get("conversation_id", None)
    try: 
        if not conversation_id:
            return JsonResponse({"error": "conversation_id is required"}, status=400)
        
        ## delete the conversation messages from cosmos first
        deleted_messages = conversation_client.delete_messages(conversation_id, user_id)

        ## Now delete the conversation 
        deleted_conversation = conversation_client.delete_conversation(user_id, conversation_id)

        return JsonResponse({"message": "Successfully deleted conversation and messages", "conversation_id": conversation_id}, status=200)
    except Exception as e:
        logging.exception("Exception in /history/delete")
        return JsonResponse({"error": str(e)}, status=500)

@require_GET
def list_conversations(request):
    authenticated_user = auth_utils.get_authenticated_user_details(request.headers)
    user_id = authenticated_user['user_principal_id']

    ## get the conversations from cosmos
    conversations = conversation_client.get_conversations(user_id)
    if not isinstance(conversations, list):
        return JsonResponse({"error": f"No conversations for {user_id} were found"}, status=404)

    ## return the conversation ids

    return JsonResponse(conversations, status=200, safe=False)

@require_POST
def get_conversation(request):
    request_body = json.loads(request.body)
    authenticated_user = auth_utils.get_authenticated_user_details(request.headers)
    user_id = authenticated_user['user_principal_id']

    ## check request for conversation_id
    conversation_id = request_body.get("conversation_id", None)
    
    if not conversation_id:
        return JsonResponse({"error": "conversation_id is required"}, status=400)

    ## get the conversation object and the related messages from cosmos
    conversation = conversation_client.get_conversation(user_id, conversation_id)
    ## return the conversation id and the messages in the bot frontend format
    if not conversation:
        return JsonResponse({"error": f"Conversation {conversation_id} was not found. It either does not exist or the logged in user does not have access to it."}, status=404)
    
    # get the messages for the conversation from cosmos
    conversation_messages = conversation_client.get_messages(user_id, conversation_id)

    ## format the messages in the bot frontend format
    messages = [{'id': msg['id'], 'role': msg['role'], 'content': msg['content'], 'createdAt': msg['createdAt']} for msg in conversation_messages]

    return JsonResponse({"conversation_id": conversation_id, "messages": messages}, status=200)

@require_POST
def rename_conversation(request):
    request_body = json.loads(request.body)
    authenticated_user = auth_utils.get_authenticated_user_details(request.headers)
    user_id = authenticated_user['user_principal_id']

    ## check request for conversation_id
    conversation_id = request_body.get("conversation_id", None)
    
    if not conversation_id:
        return JsonResponse({"error": "conversation_id is required"}, status=400)
    
    ## get the conversation from cosmos
    conversation = conversation_client.get_conversation(user_id, conversation_id)
    if not conversation:
        return JsonResponse({"error": f"Conversation {conversation_id} was not found. It either does not exist or the logged in user does not have access to it."}, status=404)

    ## update the title
    title = request_body.get("title", None)
    if not title:
        return JsonResponse({"error": "title is required"}, status=400)
    conversation['title'] = title
    updated_conversation = conversation_client.upsert_conversation(conversation)

    return JsonResponse(updated_conversation, status=200)

@require_http_methods(["DELETE"])
def delete_all_conversations(request):
    ## get the user id from the request headers
    authenticated_user = auth_utils.get_authenticated_user_details(request.headers)
    user_id = authenticated_user['user_principal_id']

    # get conversations for user
    try:
        conversations = conversation_client.get_conversations(user_id)
        if not conversations:
            return JsonResponse({"error": f"No conversations for {user_id} were found"}, status=404)
        
        # delete each conversation
        for conversation in conversations:
            ## delete the conversation messages from cosmos first
            deleted_messages = conversation_client.delete_messages(conversation['id'], user_id)

            ## Now delete the conversation 
            deleted_conversation = conversation_client.delete_conversation(user_id, conversation['id'])

        return JsonResponse({"message": f"Successfully deleted conversation and messages for user {user_id}"}, status=200)
    
    except Exception as e:
        logging.exception("Exception in /history/delete_all")
        return JsonResponse({"error": str(e)}, status=500)
    

@require_POST
def clear_messages(request):
    request_body = json.loads(request.body)
    ## get the user id from the request headers
    authenticated_user = auth_utils.get_authenticated_user_details(request.headers)
    user_id = authenticated_user['user_principal_id']
    
    ## check request for conversation_id
    conversation_id = request_body.get("conversation_id", None)
    try: 
        if not conversation_id:
            return JsonResponse({"error": "conversation_id is required"}, status=400)
        
        ## delete the conversation messages from cosmos
        deleted_messages = conversation_client.delete_messages(conversation_id, user_id)

        return JsonResponse({"message": "Successfully deleted messages in conversation", "conversation_id": conversation_id}, status=200)
    except Exception as e:
        logging.exception("Exception in /history/clear_messages")
        return JsonResponse({"error": str(e)}, status=500)

@require_GET
def get_csrf_token(request):
    return JsonResponse({'csrfToken': get_token(request)}, status=200)

@require_GET
def getSpeechToken(request):
    return synthesis.getSpeechToken()

@require_GET
def getIceToken(request):
    return synthesis.getIceToken()

@require_POST
def connectAvatar(request):
    ClientId = request.headers.get('ClientId')
    request_body = request.body.decode('utf-8')
    return synthesis.connectAvatar(ClientId,request_body)

# The API route to speak a given SSML
@require_POST
def speak(request):
    client_id = uuid.UUID(request.headers.get('ClientId'))
    try:
        spokentext = request.body.decode('utf-8')
        ttsVoice = 'vi-VN-HoaiMyNeural'
        personalVoiceSpeakerProfileID = ''
        spokenSsml = f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xmlns:mstts='http://www.w3.org/2001/mstts' xml:lang='en-US'><voice name='{ttsVoice}'><mstts:ttsembedding speakerProfileId='{personalVoiceSpeakerProfileID}'><mstts:leadingsilence-exact value='0'/>{spokentext}</mstts:ttsembedding></voice></speak>"
        result_id = synthesis.speakSsml(spokenSsml, client_id)
        return HttpResponse(result_id, status=200)
    except Exception as e:
        return HttpResponse(f"Speak failed. Error message: {e}", status=400)

# The API route to get the speaking status
@require_GET
def getSpeakingStatus(request):
    ClientId = request.headers.get('ClientId')
    return synthesis.getSpeakingStatus(ClientId)

# The API route to stop avatar from speaking
@require_POST
def stopSpeaking(request):
    synthesis.stopSpeakingInternal(uuid.UUID(request.headers.get('ClientId')))
    return HttpResponse('Speaking stopped.', status=200)

# The API route for chat
@require_POST
def chat(request):
    clientId = request.headers.get('ClientId')
    SystemPrompt = request.headers.get('SystemPrompt')
    user_query = request.body.decode('utf-8')
    return synthesis.chat(clientId, SystemPrompt, user_query)

# The API route to clear the chat history
@require_POST
def clearChatHistory(request):
    clientId = request.headers.get('ClientId')
    SystemPrompt = request.headers.get('SystemPrompt')
    return synthesis.clearChatHistory(clientId, SystemPrompt)

# The API route to disconnect the TTS avatar
@require_POST
def disconnectAvatar(request):
    ClientId = request.headers.get('ClientId')
    return synthesis.disconnectAvatar(ClientId)

# Start the speech token refresh thread
speechTokenRefereshThread = threading.Thread(target=synthesis.refreshSpeechToken)
speechTokenRefereshThread.daemon = True
speechTokenRefereshThread.start()

# Fetch ICE token at startup
synthesis.refreshIceToken()