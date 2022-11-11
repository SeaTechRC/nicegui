import shlex
from abc import ABC
from typing import Callable, Dict, List, Optional

from . import globals
from .elements.binding_mixins import BindVisibilityMixin
from .event_listener import EventListener
from .slot import Slot
from .task_logger import create_task


class Element(ABC, BindVisibilityMixin):

    def __init__(self, tag: str) -> None:
        self.client = globals.client_stack[-1]
        self.id = self.client.next_element_id
        self.client.next_element_id += 1
        self.tag = tag
        self._classes: List[str] = []
        self._style: Dict[str, str] = {}
        self._props: Dict[str, str] = {}
        self._event_listeners: List[EventListener] = []
        self._text: str = ''
        self.slots: Dict[str, Slot] = {}
        self.default_slot = self.add_slot('default')
        self.visible = True

        self.client.elements[self.id] = self
        if self.client.slot_stack:
            self.client.slot_stack[-1].children.append(self)

    def on_visibility_change(self, visible: str) -> None:
        if visible and 'hidden' in self._classes:
            self._classes.remove('hidden')
            self.update()
        if not visible and 'hidden' not in self._classes:
            self._classes.append('hidden')
            self.update()

    def add_slot(self, name: str) -> Slot:
        self.slots[name] = Slot(self, name)
        return self.slots[name]

    def __enter__(self):
        self.client.slot_stack.append(self.default_slot)
        return self

    def __exit__(self, *_):
        self.client.slot_stack.pop()

    def to_dict(self) -> Dict:
        events: Dict[str, List[str]] = {}
        for listener in self._event_listeners:
            events[listener.type] = events.get(listener.type, []) + listener.args
        return {
            'id': self.id,
            'tag': self.tag,
            'class': self._classes,
            'style': self._style,
            'props': self._props,
            'events': events,
            'text': self._text,
            'slots': {name: [child.id for child in slot.children] for name, slot in self.slots.items()},
        }

    def classes(self, add: Optional[str] = None, *, remove: Optional[str] = None, replace: Optional[str] = None):
        '''HTML classes to modify the look of the element.
        Every class in the `remove` parameter will be removed from the element.
        Classes are separated with a blank space.
        This can be helpful if the predefined classes by NiceGUI are not wanted in a particular styling.
        '''
        class_list = self._classes if replace is None else []
        class_list = [c for c in class_list if c not in (remove or '').split()]
        class_list += (add or '').split()
        class_list += (replace or '').split()
        new_classes = list(dict.fromkeys(class_list))  # NOTE: remove duplicates while preserving order
        if self._classes != new_classes:
            self._classes = new_classes
            self.update()
        return self

    def style(self, add: Optional[str] = None, *, remove: Optional[str] = None, replace: Optional[str] = None):
        '''CSS style sheet definitions to modify the look of the element.
        Every style in the `remove` parameter will be removed from the element.
        Styles are separated with a semicolon.
        This can be helpful if the predefined style sheet definitions by NiceGUI are not wanted in a particular styling.
        '''
        def parse_style(text: Optional[str]) -> Dict[str, str]:
            return dict((word.strip() for word in part.split(':')) for part in text.strip('; ').split(';')) if text else {}
        style_dict = self._style if replace is None else {}
        for key in parse_style(remove):
            del style_dict[key]
        style_dict.update(parse_style(add))
        style_dict.update(parse_style(replace))
        if self._style != style_dict:
            self._style = style_dict
            self.update()
        return self

    def props(self, add: Optional[str] = None, *, remove: Optional[str] = None):
        '''Quasar props https://quasar.dev/vue-components/button#design to modify the look of the element.
        Boolean props will automatically activated if they appear in the list of the `add` property.
        Props are separated with a blank space. String values must be quoted.
        Every prop passed to the `remove` parameter will be removed from the element.
        This can be helpful if the predefined props by NiceGUI are not wanted in a particular styling.
        '''
        def parse_props(text: Optional[str]) -> Dict[str, str]:
            if not text:
                return {}
            lexer = shlex.shlex(text, posix=True)
            lexer.whitespace = ' '
            lexer.wordchars += '=-.%'
            return dict(word.split('=', 1) if '=' in word else (word, True) for word in lexer)
        needs_update = False
        for key in parse_props(remove):
            if key in self._props:
                needs_update = True
                del self._props[key]
        for key, value in parse_props(add).items():
            if self._props.get(key) != value:
                needs_update = True
                self._props[key] = value
        if needs_update:
            self.update()
        return self

    def on(self, type: str, handler: Optional[Callable], args: List[str] = []):
        if handler:
            self._event_listeners.append(EventListener(element_id=self.id, type=type, args=args, handler=handler))
        return self

    def handle_event(self, msg: Dict) -> None:
        for listener in self._event_listeners:
            if listener.type == msg['type']:
                listener.handler(msg)

    def update(self) -> None:
        if not globals.loop:
            return
        ids: List[int] = []

        def collect_ids(id: str):
            for slot in self.client.elements[id].slots.values():
                for child in slot.children:
                    collect_ids(child.id)
            ids.append(id)
        collect_ids(self.id)
        elements = {id: self.client.elements[id].to_dict() for id in ids}
        create_task(globals.sio.emit('update', {'elements': elements}, room=str(self.client.id)))
