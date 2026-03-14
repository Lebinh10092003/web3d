# WhatsApp command format

## 1. Customer chat reply
Use this exact format:

#W4821 Your reply text here

Example:
#W4821 Thank you. We can send the quotation this afternoon.

## 2. Create or update a blog draft
Use this format:

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

## 3. Publish an already reviewed request
/blogpublish <request_id>

Example:
/blogpublish 3f1b4c2d9e1a4d33b4a4d0a2f54b8c6a

Optional schedule:
/blogpublish 3f1b4c2d9e1a4d33b4a4d0a2f54b8c6a at 2026-03-14T09:00:00+07:00

## 4. Preview an already prepared request
/blogpreview <request_id>

Expected operator flow:
1. Send `/blogpost ...`
2. Review the returned `request_id`
3. Send `/blogpreview <request_id>` to inspect
4. Send `/blogpublish <request_id>` when ready
