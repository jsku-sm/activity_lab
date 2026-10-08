"""Register with the active Streamlit runtime; cache only immutable source text."""
from functools import lru_cache
from pathlib import Path
import streamlit.components.v2 as v2
ROOT=Path(__file__).parent

@lru_cache(maxsize=1)
def source():
    return '/* classroom styles */\n'+(ROOT/'workspace.css').read_text(),(ROOT/'workspace.js').read_text()

def renderer():
    css,js=source()
    return v2.component('activity_lab_workspace',html='<div id="activity-root"></div>',css=css,js=js)

def workspace(data,key,on_event=None):
    return renderer()(data=data,key=key,default={'event':None},on_event_change=on_event or (lambda:None))
