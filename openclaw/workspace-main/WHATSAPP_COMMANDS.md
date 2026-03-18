# WhatsApp operator examples

## 1. Customer chat reply
Use this exact format:

#W4821 Your reply text here

Example:
#W4821 Thank you. We can send the quotation this afternoon.

## 2. Create a blog draft or review request
Slash commands still work and are the clearest explicit format:

/blogpost
mode: review
title: STEM robots for primary school students
summary: Quick overview of beginner friendly STEM robots and why they help problem solving.
article: Write a practical article for parents and teachers in Vietnam.
hero: https://example.com/hero.jpg
images:
- https://example.com/photo-1.jpg
- https://example.com/photo-2.jpg
video: https://www.youtube.com/watch?v=xxxxxxxxxxx
sources:
- https://official-site.example/article-a
- https://official-site.example/article-b
publish_at: 2026-03-14T09:00:00+07:00

Notes:
- `mode` can be `draft`, `review`, `publish`, or `schedule`.
- `publish_at` is required only for `schedule`.
- `article` can be omitted if you want the agent to research and write from the brief.
- `hero`, `images`, and `video` should be public URLs or attachment URLs visible to the agent.

Natural-language examples are also supported:
- `Viet bai blog ve robot STEM cho hoc sinh tieu hoc, huong toi phu huynh Viet Nam.`
- `Soan bai moi cho web ve loi ich cua lap trinh Blockly cho tre em.`
- `Chuan bi bai viet review truoc khi dang len web.`

## 3. Preview a prepared request
Specific request by id:
/blogpreview <request_id>

Latest post in the current WhatsApp chat:
- `Cho toi xem lai bai vua chuan bi`
- `Xem bai blog moi nhat trong chat nay`

## 4. Publish an already reviewed request
/blogpublish <request_id>

Example:
/blogpublish 3f1b4c2d9e1a4d33b4a4d0a2f54b8c6a

Optional schedule:
/blogpublish 3f1b4c2d9e1a4d33b4a4d0a2f54b8c6a at 2026-03-14T09:00:00+07:00

Natural-language publish examples:
- `Dang bai vua viet len web`
- `Publish bai moi nhat giup toi`

Natural-language schedule examples:
- `Len lich dang bai vua viet luc 8h sang mai`
- `Dang bai moi nhat vao 2026-03-20T08:00:00+07:00`

Expected operator flow:
1. Create a new post with `/blogpost ...` or a natural-language request.
2. Review the returned `request_id` and blog URL.
3. Preview with `/blogpreview <request_id>` or `Cho toi xem lai bai vua chuan bi`.
4. Publish with `/blogpublish <request_id>` or `Dang bai vua viet len web`.

Notes:
- Slash commands are optional shortcuts, not the only supported input format.
- When the operator says `bai vua viet` or `bai moi nhat`, the agent should resolve that to the latest blog request in the same WhatsApp chat only.
