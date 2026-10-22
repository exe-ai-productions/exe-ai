"""The view of a chosen schedule in the pop-up: it is one column wide, so the
four facts of the schedule always stand two by two and no word of them is cut
in the middle where it fits a line; Start stands at the left and the pen and
the bin at the right, one size; on the phone Start stands over the whole width
and the two signs under it.

What these checks read is the style block of the page. The phone's rules,
written under `html[data-phone]`, are the ones that make the signs a
fingertip tall.
"""

from __future__ import annotations

from tests.cronjob_style import PHONE, base_rules, declared, pixels, style


def test_the_pop_up_is_one_column_wide_and_asks_no_container_width_of_the_view():
    # The page lays its two columns out by its own width; the pop-up asks for no
    # container width of its own.
    assert "@container" not in style().replace("@container cronjobs-page (max-width: 640px)", "")
    assert pixels(declared(base_rules()[".popup"], "width")) == [340]


def test_a_word_of_the_four_facts_breaks_only_where_it_does_not_fit_a_line():
    assert declared(base_rules()[".zelle"], "overflow-wrap") == "break-word"


def test_the_four_facts_stand_two_by_two():
    assert declared(base_rules()[".raster"], "grid-template-columns") == "repeat(2, minmax(0, 1fr))"


def test_start_stands_at_the_left_and_the_two_signs_at_the_right():
    base = base_rules()
    assert declared(base[".knoepfe"], "display") == "flex"
    assert declared(base[".knoepfe"], "justify-content") == "space-between"
    assert declared(base[".signpair"], "display") == "inline-flex"


def test_the_pen_and_the_bin_are_one_size_and_only_the_bin_is_red():
    base = base_rules()
    size = (declared(base[".signbutton"], "width"), declared(base[".signbutton"], "height"))
    assert size == ("36px", "36px")
    assert "--rot" not in base[".signbutton"]
    assert declared(base[".signbutton.danger"], "color") == "var(--rot-text)"


def test_the_schedule_in_full_scrolls_in_itself_so_the_pop_up_clips_nothing_it_needs():
    assert declared(base_rules()[".einzel"], "overflow-y") == "auto"


def test_the_rules_of_the_phone_put_start_over_the_width_and_the_signs_under_it():
    base = base_rules()
    assert declared(base[f"{PHONE} .zelle"], "overflow-wrap") == "break-word"
    assert declared(base[f"{PHONE} .knoepfe"], "display") == "grid"
    assert declared(base[f"{PHONE} .knoepfe"], "grid-template-columns") == "minmax(0, 1fr)"
    assert declared(base[f"{PHONE} .knoepfe"], "grid-auto-flow") == "row"
    assert declared(base[f"{PHONE} .knopf"], "height") == "44px"
    assert declared(base[f"{PHONE} .signpair"], "justify-content") == "flex-end"
    assert declared(base[f"{PHONE} .signbutton"], "width") == "44px"
    assert declared(base[f"{PHONE} .signbutton"], "height") == "44px"
