import json

from django.contrib import messages as django_messages


class HtmxMessageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.headers.get("HX-Request") != "true":
            return response

        storage = django_messages.get_messages(request)
        message_list = []
        for message in storage:
            text = getattr(message, "message", None)
            if text is None:
                text = str(message)
            text = str(text).strip()
            if not text:
                continue
            message_list.append({"level": message.tags, "text": text})

        if not message_list:
            return response

        payload = {"notify": message_list}
        existing = response.headers.get("HX-Trigger")
        if existing:
            try:
                existing_payload = json.loads(existing)
                if isinstance(existing_payload, dict):
                    existing_notify = existing_payload.get("notify")
                    if isinstance(existing_notify, list):
                        existing_notify.extend(message_list)
                    else:
                        existing_payload["notify"] = message_list
                    payload = existing_payload
            except Exception:
                payload = {"notify": message_list}

        response.headers["HX-Trigger"] = json.dumps(payload)
        return response
