"""Same-class method calls must not bind to another class's method.

``label_to_nid`` is one file-wide map. A later ``bark`` overwrote an earlier
one, so ``Dog.speak``'s ``self.bark()`` / ``this.bark()`` / bare ``bark()``
became an EXTRACTED ``calls`` edge to ``Cat.bark``. These tests fail on that
resolution: the edge must land on Dog's own method, and an inherited
``self.bark()`` must not land on an unrelated ``Cat.bark``.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from graphify.extract import extract

# One file per language. Dog is declared first; Cat's same-named method used
# to win because it was inserted last.
_CASES: list[tuple[str, str, str, str, str]] = [
    (
        "zoo.py",
        "class Dog:\n"
        "    def speak(self):\n"
        "        return self.bark()\n"
        "    def bark(self):\n"
        "        return 'woof'\n"
        "class Cat:\n"
        "    def speak(self):\n"
        "        return 'meow'\n"
        "    def bark(self):\n"
        "        return 'hiss'\n",
        "Dog",
        ".speak()",
        ".bark()",
    ),
    (
        "zoo.js",
        "class Dog {\n"
        "  speak() { return this.bark(); }\n"
        "  bark() { return 'woof'; }\n"
        "}\n"
        "class Cat {\n"
        "  speak() { return 'meow'; }\n"
        "  bark() { return 'hiss'; }\n"
        "}\n",
        "Dog",
        ".speak()",
        ".bark()",
    ),
    (
        "zoo.ts",
        "class Dog {\n"
        "  speak(): string { return this.bark(); }\n"
        "  bark(): string { return 'woof'; }\n"
        "}\n"
        "class Cat {\n"
        "  speak(): string { return 'meow'; }\n"
        "  bark(): string { return 'hiss'; }\n"
        "}\n",
        "Dog",
        ".speak()",
        ".bark()",
    ),
    (
        "Zoo.java",
        "class Dog {\n"
        "    String speak() { return bark(); }\n"
        "    String bark() { return \"woof\"; }\n"
        "}\n"
        "class Cat {\n"
        "    String speak() { return \"meow\"; }\n"
        "    String bark() { return \"hiss\"; }\n"
        "}\n",
        "Dog",
        ".speak()",
        ".bark()",
    ),
    (
        "Zoo.cs",
        "class Dog {\n"
        "    public string Speak() { return Bark(); }\n"
        "    public string Bark() { return \"woof\"; }\n"
        "}\n"
        "class Cat {\n"
        "    public string Speak() { return \"meow\"; }\n"
        "    public string Bark() { return \"hiss\"; }\n"
        "}\n",
        "Dog",
        ".Speak()",
        ".Bark()",
    ),
    (
        "zoo.cpp",
        "class Dog {\n"
        "public:\n"
        "    const char* speak() { return bark(); }\n"
        "    const char* bark() { return \"woof\"; }\n"
        "};\n"
        "class Cat {\n"
        "public:\n"
        "    const char* speak() { return \"meow\"; }\n"
        "    const char* bark() { return \"hiss\"; }\n"
        "};\n",
        "Dog",
        ".speak()",
        ".bark()",
    ),
    (
        "zoo.go",
        "package zoo\n"
        "type Dog struct{}\n"
        "type Cat struct{}\n"
        "func (d Dog) Speak() string { return d.Bark() }\n"
        "func (d Dog) Bark() string  { return \"woof\" }\n"
        "func (c Cat) Speak() string { return \"meow\" }\n"
        "func (c Cat) Bark() string  { return \"hiss\" }\n",
        "Dog",
        ".Speak()",
        ".Bark()",
    ),
    (
        "zoo.rs",
        "struct Dog;\n"
        "struct Cat;\n"
        "impl Dog {\n"
        "    fn speak(&self) -> &str { self.bark() }\n"
        "    fn bark(&self) -> &str { \"woof\" }\n"
        "}\n"
        "impl Cat {\n"
        "    fn speak(&self) -> &str { \"meow\" }\n"
        "    fn bark(&self) -> &str { \"hiss\" }\n"
        "}\n",
        "Dog",
        ".speak()",
        ".bark()",
    ),
    (
        "zoo.rb",
        "class Dog\n"
        "  def speak\n"
        "    bark\n"
        "  end\n"
        "  def bark\n"
        "    'woof'\n"
        "  end\n"
        "end\n"
        "class Cat\n"
        "  def speak\n"
        "    'meow'\n"
        "  end\n"
        "  def bark\n"
        "    'hiss'\n"
        "  end\n"
        "end\n",
        "Dog",
        ".speak()",
        ".bark()",
    ),
    (
        "zoo.php",
        "<?php\n"
        "class Dog {\n"
        "    function speak() { return $this->bark(); }\n"
        "    function bark() { return 'woof'; }\n"
        "}\n"
        "class Cat {\n"
        "    function speak() { return 'meow'; }\n"
        "    function bark() { return 'hiss'; }\n"
        "}\n",
        "Dog",
        ".speak()",
        ".bark()",
    ),
    (
        "zoo.kt",
        "class Dog {\n"
        "    fun speak(): String = bark()\n"
        "    fun bark(): String = \"woof\"\n"
        "}\n"
        "class Cat {\n"
        "    fun speak(): String = \"meow\"\n"
        "    fun bark(): String = \"hiss\"\n"
        "}\n",
        "Dog",
        ".speak()",
        ".bark()",
    ),
    (
        "zoo.swift",
        "class Dog {\n"
        "    func speak() -> String { return bark() }\n"
        "    func bark() -> String { return \"woof\" }\n"
        "}\n"
        "class Cat {\n"
        "    func speak() -> String { return \"meow\" }\n"
        "    func bark() -> String { return \"hiss\" }\n"
        "}\n",
        "Dog",
        ".speak()",
        ".bark()",
    ),
]


def _extract(tmp_path: Path, filename: str, source: str) -> dict:
    path = tmp_path / filename
    path.write_text(source, encoding="utf-8")
    old = os.getcwd()
    try:
        os.chdir(tmp_path)
        return extract([path], cache_root=Path(tempfile.mkdtemp()))
    finally:
        os.chdir(old)


def _method_id(result: dict, class_label: str, method_label: str) -> str:
    classes = [n["id"] for n in result["nodes"] if n.get("label") == class_label]
    assert len(classes) == 1, f"expected one {class_label!r}, got {classes}"
    class_id = classes[0]
    nodes = {n["id"]: n for n in result["nodes"]}
    found = [
        e["target"]
        for e in result["edges"]
        if e.get("relation") == "method"
        and e.get("source") == class_id
        and nodes.get(e.get("target"), {}).get("label") == method_label
    ]
    assert len(found) == 1, f"no single {class_label}.{method_label}, got {found}"
    return found[0]


def _calls(result: dict, src: str, tgt: str) -> list[dict]:
    return [
        e
        for e in result["edges"]
        if e.get("relation") == "calls" and e.get("source") == src and e.get("target") == tgt
    ]


@pytest.mark.parametrize(
    ("filename", "source", "class_label", "speak", "bark"),
    _CASES,
    ids=[name for name, *_rest in _CASES],
)
def test_self_call_binds_to_own_class_not_the_later_class(
    tmp_path: Path, filename: str, source: str, class_label: str, speak: str, bark: str,
) -> None:
    result = _extract(tmp_path, filename, source)
    dog_speak = _method_id(result, class_label, speak)
    dog_bark = _method_id(result, class_label, bark)
    cat_bark = _method_id(result, "Cat", bark)
    own = _calls(result, dog_speak, dog_bark)
    assert own, f"{filename}: {class_label}.{speak} did not call its own {bark}"
    assert all(e.get("confidence") == "EXTRACTED" for e in own)
    assert not _calls(result, dog_speak, cat_bark), (
        f"{filename}: {class_label}.{speak} bound to Cat.{bark}"
    )


def test_python_module_level_call_still_resolves(tmp_path: Path) -> None:
    result = _extract(
        tmp_path,
        "mod.py",
        "def helper():\n"
        "    return 1\n"
        "class Dog:\n"
        "    def speak(self):\n"
        "        return helper()\n"
        "class Cat:\n"
        "    def bark(self):\n"
        "        return 'hiss'\n",
    )
    speak = _method_id(result, "Dog", ".speak()")
    helper = next(n["id"] for n in result["nodes"] if n.get("label") == "helper()")
    assert _calls(result, speak, helper)
    assert not _calls(result, speak, _method_id(result, "Cat", ".bark()"))


def test_python_other_receiver_is_not_pulled_onto_the_caller_class(tmp_path: Path) -> None:
    """``other.bark()`` is not a self/this call and must not become Dog.bark."""
    result = _extract(
        tmp_path,
        "other.py",
        "class Dog:\n"
        "    def speak(self, other):\n"
        "        return other.bark()\n"
        "    def bark(self):\n"
        "        return 'woof'\n"
        "class Cat:\n"
        "    def bark(self):\n"
        "        return 'hiss'\n",
    )
    speak = _method_id(result, "Dog", ".speak()")
    assert not _calls(result, speak, _method_id(result, "Dog", ".bark()"))
    assert not _calls(result, speak, _method_id(result, "Cat", ".bark()"))


def test_inherited_self_call_does_not_bind_to_unrelated_class(tmp_path: Path) -> None:
    """Dog(Base).speak calls self.bark defined on Base. Cat.bark must not win."""
    result = _extract(
        tmp_path,
        "inherit.py",
        "class Base:\n"
        "    def bark(self):\n"
        "        return 'woof'\n"
        "class Dog(Base):\n"
        "    def speak(self):\n"
        "        return self.bark()\n"
        "class Cat:\n"
        "    def bark(self):\n"
        "        return 'hiss'\n",
    )
    speak = _method_id(result, "Dog", ".speak()")
    cat_bark = _method_id(result, "Cat", ".bark()")
    assert not _calls(result, speak, cat_bark)
