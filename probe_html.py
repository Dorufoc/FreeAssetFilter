import markdown
from pygments.formatters import HtmlFormatter

md = markdown.Markdown(
    extensions=['fenced_code', 'codehilite'],
    extension_configs={'codehilite': {'css_class': 'highlight', 'use_pygments': True}}
)

text = """
```python
def hello():
    pass
```
"""
html = md.convert(text)
print('=== BODY HTML ===')
print(html)
print()
print('=== PYGMENTS CSS (default) ===')
print(HtmlFormatter(style='default').get_style_defs('.highlight'))
