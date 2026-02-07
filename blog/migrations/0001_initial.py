from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import uuid


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Post',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=220, verbose_name='Title')),
                ('slug', models.SlugField(blank=True, max_length=240, unique=True, verbose_name='Slug')),
                ('summary', models.CharField(blank=True, max_length=320, verbose_name='Summary')),
                ('body', models.TextField(blank=True, verbose_name='Body (legacy / fallback)')),
                ('hero_image_url', models.URLField(blank=True, max_length=500, verbose_name='Hero image URL')),
                ('seo_title', models.CharField(blank=True, max_length=240, verbose_name='SEO title')),
                ('seo_description', models.CharField(blank=True, max_length=320, verbose_name='SEO description')),
                ('status', models.CharField(choices=[('DRAFT', 'Draft'), ('PENDING_REVIEW', 'Pending review'), ('SCHEDULED', 'Scheduled'), ('PUBLISHED', 'Published')], default='DRAFT', max_length=20, verbose_name='Status')),
                ('published_at', models.DateTimeField(default=django.utils.timezone.now, verbose_name='Publish at')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='blog_posts', to=settings.AUTH_USER_MODEL, verbose_name='Author')),
            ],
            options={
                'verbose_name': 'Blog post',
                'verbose_name_plural': 'Blog posts',
                'ordering': ['-published_at', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='PostBlock',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('position', models.PositiveIntegerField(default=1, verbose_name='Order')),
                ('type', models.CharField(choices=[('TEXT', 'Text'), ('IMAGE', 'Image'), ('VIDEO', 'Video'), ('GALLERY', 'Gallery'), ('QUOTE', 'Quote'), ('DIVIDER', 'Divider')], max_length=20, verbose_name='Type')),
                ('text', models.TextField(blank=True)),
                ('media_url', models.URLField(blank=True, max_length=600)),
                ('caption', models.CharField(blank=True, max_length=300)),
                ('alt_text', models.CharField(blank=True, max_length=200)),
                ('align', models.CharField(blank=True, help_text='left|center|right|wide|full', max_length=20)),
                ('data', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('post', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='blocks', to='blog.post')),
            ],
            options={
                'verbose_name': 'Block',
                'verbose_name_plural': 'Blocks',
                'ordering': ['position', 'created_at'],
            },
        ),
        migrations.CreateModel(
            name='PostRevision',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('is_autosave', models.BooleanField(default=False)),
                ('payload', models.JSONField(blank=True, default=dict)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('post', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='revisions', to='blog.post')),
            ],
            options={
                'verbose_name': 'Revision',
                'verbose_name_plural': 'Revisions',
                'ordering': ['-created_at'],
            },
        ),
    ]
