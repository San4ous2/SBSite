from django.db import models

class QuizResult(models.Model):
    score = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Результат: {self.score} (Дата: {self.created_at})"
