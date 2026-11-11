from conftest import make_item

from civitai_widget import feed


def test_thumbnail_url_rewrites_transform_segment():
    base = "https://image.civitai.com/key/uuid"
    assert feed.thumbnail_url(f"{base}/original=true/pic.jpeg", 450) == f"{base}/width=450/pic.jpeg"
    assert feed.thumbnail_url(f"{base}/width=1024/pic.jpeg", 450) == f"{base}/width=450/pic.jpeg"
    assert feed.thumbnail_url(f"{base}/original=true,quality=90/pic.jpeg", 450) == f"{base}/width=450/pic.jpeg"


def test_thumbnail_url_leaves_unknown_urls_alone():
    url = "https://example.com/images/pic.jpeg?x=1"
    assert feed.thumbnail_url(url) == url


def test_reaction_count_ignores_missing_and_comments():
    assert feed.reaction_count(make_item(1)) == 10
    assert feed.reaction_count({"stats": None}) == 0
    assert feed.reaction_count({}) == 0


def test_format_count():
    assert feed.format_count(999) == "999"
    assert feed.format_count(1741) == "1.7k"
    assert feed.format_count(25300) == "25k"
    assert feed.format_count(2_400_000) == "2.4M"


def test_clean_items_drops_videos_duplicates_and_broken_entries():
    raw = [
        make_item(1),
        make_item(2, type="video"),
        make_item(3, url=""),
        make_item(1),
        "garbage",
        {"type": "image", "url": "x"},
        make_item(4),
    ]
    assert feed.item_ids(feed.clean_items(raw, allow_nsfw=False)) == ["1", "4"]


def test_clean_items_enforces_sfw_on_the_client():
    raw = [
        make_item(1),
        make_item(2, nsfw=True),
        make_item(3, nsfwLevel="Mature"),
        make_item(4, nsfwLevel=4),
        make_item(5, nsfwLevel=1),
        make_item(6, nsfw="X"),
    ]
    assert feed.item_ids(feed.clean_items(raw, allow_nsfw=False)) == ["1", "5"]
    assert len(feed.clean_items(raw, allow_nsfw=True)) == 6


def test_paginate_keeps_every_item():
    items = [make_item(i) for i in range(14)]
    pages = feed.paginate(items, 6)
    assert [len(page) for page in pages] == [6, 6, 2]
    assert [item for page in pages for item in page] == items
    assert feed.paginate([], 6) == []


def test_base_models_and_filter():
    items = [make_item(1, baseModel="SDXL"), make_item(2, baseModel="Flux"), make_item(3, baseModel="SDXL"), make_item(4)]
    assert feed.base_models(items) == [("SDXL", 2), ("Flux", 1)]
    assert feed.item_ids(feed.filter_by_model(items, "SDXL")) == ["1", "3"]
    assert len(feed.filter_by_model(items, None)) == 4


def test_query_params_and_key():
    query = feed.FeedQuery(nsfw=False, period="Week", sort="Most Reactions")
    assert query.params() == {"sort": "Most Reactions", "period": "Week", "limit": "100", "nsfw": "false"}
    assert query.params("abc")["cursor"] == "abc"
    assert query.key() != feed.FeedQuery(nsfw=True).key()
    assert query.key() == feed.FeedQuery().key()
