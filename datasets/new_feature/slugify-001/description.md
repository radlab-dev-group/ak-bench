# Implement `slugify` from the specification

`textkit.slugify` in `src/textkit/slugify.py` is declared, documented and
tested, but its body raises `NotImplementedError`. Write it.

## Contract

`slugify(text: str, separator: str = "-") -> str` builds a URL slug:

1. The result is lowercase.
2. ASCII letters (`a-z`, `A-Z`) and digits (`0-9`) are kept.
3. Every other character — including spaces, punctuation and non-ASCII letters
   such as `ż` or `é` — acts as a separator. There is no transliteration.
4. A run of one or more separator characters collapses to a single `separator`.
5. The result never starts or ends with `separator`.
6. An input with no letters or digits yields an empty string.
7. `separator` is a single character and is inserted verbatim.

## Examples

| call | result |
|---|---|
| `slugify("Hello World")` | `"hello-world"` |
| `slugify("Hello, World!")` | `"hello-world"` |
| `slugify("one -- two ___ three")` | `"one-two-three"` |
| `slugify("  --Trimmed--  ")` | `"trimmed"` |
| `slugify("AK-Bench 2026")` | `"ak-bench-2026"` |
| `slugify("Zażółć")` | `"za"` |
| `slugify("Zażółć gęślami")` | `"za-g-lami"` |
| `slugify("!!!")` | `""` |
| `slugify("")` | `""` |
| `slugify("Hello World", separator="_")` | `"hello_world"` |

Applying `slugify` to its own result must not change it again.

## Boundaries

- Implement it in `src/textkit/slugify.py`; the public API of the `textkit`
  package stays as it is.
- Do not modify the tests and do not add third-party dependencies — the standard
  library is enough.
- The repository's own test suite (`pytest`) has to stay green, so
  `textkit.casefold_word` must keep working.
