from scripts.fetch_avatars import parse_list

HTML = """
<div class="st-heroes__types"><a class="st-heroes__item--fake">x</a></div>
<div class="st-heroes__list">
  <a href="https://lienquan.garena.vn/hoc-vien/tuong-skin/d/flowborn-2/" class="st-heroes__item"
     data-keyword="flowborn" data-type="[29]" data-tag="">
    <div class="st-heroes__item--img"><img src="https://x/a.jpg" alt="Flowborn"></div>
    <h2 class="st-heroes__item--name">
      Flowborn          </h2>
  </a>
  <a href="https://lienquan.garena.vn/hoc-vien/tuong-skin/d/flowborn/" class="st-heroes__item" data-type="[33, 32]">
    <div class="st-heroes__item--img"><img src="https://x/b.jpg"/></div>
    <h2 class="st-heroes__item--name">Flowborn</h2>
  </a>
</div>
<a class="st-heroes__item" href="/outside/list/">not in list</a>
"""


def test_parse_list():
    heroes = parse_list(HTML)
    assert [(h.vn_id, h.vn_name, h.img, h.classes) for h in heroes] == [
        ("flowborn-2", "Flowborn", "https://x/a.jpg", ["法師"]),
        ("flowborn", "Flowborn", "https://x/b.jpg", ["射手", "刺客"]),
    ]
