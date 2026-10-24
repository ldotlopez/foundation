from itertools import chain

import bs4
import markdownify as markdownify_
import trafilatura

# import readability


#
# Load content
def soupify(html: str) -> bs4.BeautifulSoup:
    """Convert HTML to a BeautifulSoup object."""
    return bs4.BeautifulSoup(html, features="html5lib")


def head_meta_get_value(html: bs4.Tag, attr_filter: dict | None = None) -> str:
    """Extract and return the stripped 'content' value of a <meta> tag in <head>.

    Args:
        html: The parsed HTML (or a tag containing a <head>) to search.
        attr_filter: Optional dict of attributes used to locate the target
            <meta> tag (e.g. {"name": "description"}). Defaults to no filter.

    Returns:
        The stripped string value of the meta tag's "content" attribute.

    Raises:
        ValueError: If no <head> tag is found, no matching <meta> tag is
            found, or the matching <meta> tag has no "content" attribute.
        NotImplementedError: If the "content" attribute value is not a string.
    """
    attr_filter = attr_filter if attr_filter is not None else {}

    if (head_tag := html.find("head")) is None:
        raise ValueError("No <head> tag found in the provided HTML.")

    if (meta_tag := head_tag.find("meta", attrs=attr_filter)) is None:
        raise ValueError(f"No <meta> tag found matching filter: {attr_filter!r}")

    try:
        content = meta_tag.attrs["content"]
    except KeyError as e:
        raise ValueError(
            f"Matching <meta> tag has no 'content' attribute: {meta_tag!r}"
        ) from e

    if not isinstance(content, str):
        raise NotImplementedError(
            f"Expected 'content' attribute to be a string, got {type(content)!r}"
        )

    return content.strip()


def head_meta_get_value_by_name(html: bs4.Tag, name: str) -> str:
    """Get a <head> <meta> tag's content value by its "name" attribute.

    Args:
        html: The parsed HTML (or a tag containing a <head>) to search.
        name: The value of the "name" attribute to match against.

    Returns:
        The stripped string value of the matching meta tag's "content" attribute.
    """
    return head_meta_get_value(html, attr_filter={"name": name})


def head_meta_get_value_by_property(html: bs4.Tag, property: str) -> str:
    """Get a <head> <meta> tag's content value by its "property" attribute.

    Args:
        html: The parsed HTML (or a tag containing a <head>) to search.
        property: The value of the "property" attribute to match against
            (e.g. an Open Graph property like "og:title").

    Returns:
        The stripped string value of the matching meta tag's "content" attribute.
    """
    return head_meta_get_value(html, attr_filter={"property": property})


def find_canonical_url(html: bs4.Tag | str) -> str | None:
    """Find the canonical URL a page declares about itself.

    Looks for <link rel="canonical"> (RFC 6596) first, then
    <meta property="og:url">, both inside <head>. Unlike head_meta_get_value(),
    a missing value is not an error: many pages declare no canonical URL.

    Args:
        html: The parsed HTML or a raw HTML string (parsed with soupify()).

    Returns:
        The stripped URL as declared, which may be relative (resolve it with
        urljoin() against the page URL), or None if the page declares none.
    """
    soup = soupify(html) if isinstance(html, str) else html
    link = soup.select_one('head link[rel~="canonical"][href]')
    if link is not None and (url := str(link["href"]).strip()):
        return url
    meta = soup.select_one('head meta[property="og:url"][content]')
    if meta is not None and (url := str(meta["content"]).strip()):
        return url
    return None


#
# Clean up  and manipulate


def prune_to_spine(node: bs4.Tag, stop_at: bs4.Tag | None = None) -> bs4.Tag:
    """Prune the DOM containing `node` down to its ancestor spine.

    Keeps `node` (with its full subtree untouched) and every ancestor
    from `node` up to and including `stop_at`. Ancestor tags are kept
    with their original attributes intact. Any sibling of `node` or of
    any ancestor along the path — i.e. anything not directly on the
    root-to-`node` path — is removed.

    If `stop_at` is None, prunes all the way to the outermost tag
    (typically `<html>`), skipping the BeautifulSoup document wrapper
    itself.

    Mutates the tree in place. Returns the top-most surviving ancestor
    (i.e. `stop_at`, or the root tag reached).
    """
    current = node
    for parent in current.parents:
        if not isinstance(parent, bs4.Tag) or parent.name == "[document]":
            break

        for sibling in chain(current.next_siblings, current.previous_siblings):
            sibling.extract()

        current = parent
        if parent is stop_at:
            break

    return current


def drop_selector(tag: bs4.Tag, selector: str) -> bs4.Tag:
    """Remove all elements matching a single CSS selector from a tag.

    Args:
        tag: The BeautifulSoup tag to modify in place.
        selector: A CSS selector identifying elements to remove.

    Returns:
        The same tag, with matching elements removed.
    """
    return drop_selectors(tag, [selector])


def drop_selectors(tag: bs4.Tag, selectors: list[str]) -> bs4.Tag:
    """Remove all elements matching any of the given CSS selectors from a tag.

    Args:
        tag: The BeautifulSoup tag to modify in place.
        selectors: A list of CSS selectors identifying elements to remove.

    Returns:
        The same tag, with matching elements removed.
    """
    for selector in selectors:
        to_drop = tag.select(selector)
        for x in to_drop:
            x.decompose()

    return tag


#
# Extract content
def extract(source: bs4.Tag | str, output_format: str = "html") -> str:
    """Extract the main content from HTML using trafilatura.

    Args:
        source: The HTML to extract content from, either as a BeautifulSoup
            tag or a raw HTML string.
        output_format: The desired output format for trafilatura (e.g.
            "html", "markdown", "txt"). Defaults to "html".

    Returns:
        The extracted content in the requested format.
    """
    if isinstance(source, bs4.Tag):
        source = str(source)

    if ret := trafilatura.extract(source, output_format=output_format):
        return ret
    else:
        raise ValueError("No content could be extracted from the provided HTML.")


def markdownify(source: bs4.Tag | str) -> str:
    """Convert HTML to Markdown."""

    if isinstance(source, bs4.Tag):
        source = str(source)

    if ret := markdownify_.markdownify(source, heading_style="ATX"):
        return ret
    else:
        raise ValueError("No content could be extracted from the provided HTML.")


# def summarize(input: bs4.Tag | str) -> str:
#     if isinstance(input, bs4.Tag):
#         input = str(input)
#
#     return readability.Document(input).summary()
