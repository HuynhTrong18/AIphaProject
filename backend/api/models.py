from django.db import models
import uuid

# Create your models here.

class Conversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=255)
    user_id = models.CharField(max_length=255)
    title = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-updated_at']
        db_table = 'api_conversation'
    
    def __str__(self):
        return str(self.title) or str(self.id)

class Message(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=255)
    conversation = models.ForeignKey(Conversation, related_name='messages', on_delete=models.CASCADE)
    user_id = models.CharField(max_length=255)
    role = models.CharField(max_length=50)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['created_at']
        db_table = 'api_message'
    
    def __str__(self):
        return f'{self.role}: {self.content}'