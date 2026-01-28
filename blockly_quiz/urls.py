from django.urls import path

from . import views


app_name = "blockly_quiz"

urlpatterns = [
    path("", views.quiz_list, name="list"),
    path("scores/", views.attempt_list, name="scores"),
    path("scores/admin/", views.attempt_admin_list, name="scores-admin"),
    path("scores/export/", views.attempt_export_csv, name="scores-export"),
    path("scores/export/pdf/", views.attempt_export_pdf, name="scores-export-pdf"),
    path("classrooms/", views.classroom_list, name="classroom-list"),
    path("classrooms/<slug:slug>/", views.classroom_detail, name="classroom-detail"),
    path("random/", views.random_quiz, name="random"),
    path("random/start/", views.random_quiz_start, name="random-start"),
    path("random/<slug:slug>/discard/", views.random_quiz_discard, name="random-discard"),
    path("tools/blockly/", views.blockly_guide, name="tool-blockly"),
    path("tools/scratch/", views.tool_redirect, name="tool-scratch"),
    path("<slug:slug>/", views.quiz_detail, name="detail"),
    path("<slug:slug>/play/", views.quiz_play, name="play"),
    path("<slug:slug>/start/", views.quiz_start, name="start"),
    path("attempts/<int:attempt_id>/", views.attempt_take, name="attempt"),
    path("attempts/<int:attempt_id>/answer/", views.attempt_answer, name="answer"),
    path("attempts/<int:attempt_id>/review/", views.attempt_review, name="review"),
    path("api/quizzes/<slug:slug>/", views.api_quiz_payload, name="api-quiz"),
    path("api/quizzes/<slug:slug>/submit/", views.api_quiz_submit, name="api-submit"),
    path("api/attempts/<int:attempt_id>/", views.api_attempt_detail, name="api-attempt"),
]
