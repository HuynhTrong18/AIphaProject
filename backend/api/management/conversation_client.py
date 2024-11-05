from django.utils import timezone
from ..models import Conversation, Message
from django.core.exceptions import ObjectDoesNotExist

def ensure():
    """
    Check if the models are properly set up.
    """
    try:
        Conversation.objects.first()
        Message.objects.first()
        return True
    except:
        return False

def create_conversation(user_id, title=''):
    conversation = Conversation.objects.create(
        type='conversation',
        user_id=user_id,
        title=title
    )
    return conversation

def conversation_as_json(conversation: Conversation):
    return {
        'id': str(conversation.id),  
        'type': conversation.type,
        'createdAt': conversation.created_at.isoformat(),
        'updatedAt': conversation.updated_at.isoformat(),
        'userId': conversation.user_id,
        'title': conversation.title
    }

def upsert_conversation(conversation_data):
    """
    Upsert a conversation based on provided data.
    """
    conversation_id = conversation_data.get('id')
    if conversation_id:
        try:
            conversation = Conversation.objects.get(id=conversation_id)
            conversation.title = conversation_data.get('title', conversation.title)
            conversation.updated_at = timezone.now()
            conversation.save()
        except ObjectDoesNotExist:
            conversation = Conversation.objects.create(
                type='conversation',
                id=conversation_id,
                user_id=conversation_data['user_id'],
                title=conversation_data.get('title', '')
            )
    else:
        conversation = Conversation.objects.create(
            type='conversation',
            user_id=conversation_data['user_id'],
            title=conversation_data.get('title', '')
        )
    return conversation_as_json(conversation)

def delete_conversation(user_id, conversation_id):
    try:
        conversation = Conversation.objects.get(id=conversation_id, user_id=user_id)
        conversation.delete()
        return True
    except ObjectDoesNotExist:
        return False

def delete_messages(conversation_id, user_id):
    try:
        messages = Message.objects.filter(conversation__id=conversation_id, user_id=user_id)
        deleted_count = messages.delete()
        return deleted_count
    except:
        return 0

def get_conversations(user_id, sort_order='DESC'):
    if sort_order.upper() == 'ASC':
        conversations = Conversation.objects.filter(user_id=user_id).order_by('updated_at')
    else:
        conversations = Conversation.objects.filter(user_id=user_id).order_by('-updated_at')
    response_data = []
    for conversation in conversations:
        response_data.append(conversation_as_json(conversation))
    return response_data

def get_conversation(user_id, conversation_id):
    try:
        conversation = Conversation.objects.get(id=conversation_id, user_id=user_id)
        return conversation_as_json(conversation)
    except ObjectDoesNotExist:
        return None

def create_message(conversation_id, user_id, input_message: dict):
    try:
        conversation = Conversation.objects.get(id=conversation_id, user_id=user_id)
        message = Message.objects.create(
            type='message',
            conversation=conversation,
            user_id=user_id,
            role=input_message['role'],
            content=input_message['content']
        )
        # Update the conversation's updated_at timestamp
        conversation.updated_at = timezone.now()
        conversation.save()
        return message
    except ObjectDoesNotExist:
        return None

def get_messages(user_id, conversation_id):
    try:
        messages = Message.objects.filter(conversation__id=conversation_id, user_id=user_id).order_by('created_at')
        response_data = []
        for message in messages:
            response_data.append(message_as_json(message))
        return response_data
    except:
        return []
    
def message_as_json(message: Message):
    return {
        'id': str(message.id),
        'type': message.type,
        'userId' : message.user_id,
        'createdAt': message.created_at.isoformat(),
        'updatedAt': message.updated_at.isoformat(),
        'conversationId' : message.conversation.id,
        'role': message.role,
        'content': message.content
    }
