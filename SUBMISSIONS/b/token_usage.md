# Token usage

Built by `our_work/token_usage.py` from the responses saved on disk: extraction pages, including the failed
`.raw` attempts, and every paid answering request. *Prompt* = input tokens, the page image included for
the extraction. *Completion* = output tokens, which **include** the *reasoning* tokens. All models were
free-tier (cost 0 $).

Steps 2 (review: checkbox snapping, patches) and 4 (writing the PDFs) are local code and use **no tokens**.
Not counted below: OpenRouter refusals with "rate-limited" (HTTP 429), which produce no tokens; the
very first connectivity test; and the first version of the form_01 page 1 prompt (replaced, not saved).

## Summary per form

| form | step | requests | prompt | completion | of which reasoning | total | model time (s) | models |
|---|---|---|---|---|---|---|---|---|
| form_01 | 1. Reading the scans | 2 | 5,320 | 8,199 | 4,211 | 13,519 | 130 | qwen3.8-27b |
| form_01 | 3. Answering | 1 | 8,032 | 9,883 | 6,390 | 17,915 | 257 | qwen3.8-27b |
| form_02 | 1. Reading the scans | 4 | 10,596 | 21,231 | 13,565 | 31,827 | 376 | nemotron-3-nano-omni-30b-a3b-reasoning, qwen3.8-27b |
| form_02 | 3. Answering | 2 | 19,762 | 23,646 | 20,285 | 43,408 | 471 | qwen3.8-27b |
| form_03 | 1. Reading the scans | 11 | 27,156 | 50,815 | 38,907 | 77,971 | 780 | dots-3-note-preview, nemotron-3-nano-omni-30b-a3b-reasoning, qwen3.8-27b |
| form_03 | 3. Answering | 2 | 21,919 | 14,319 | 4,425 | 36,238 | 178 | qwen3.8-27b |
| form_04 | 1. Reading the scans | 4 | 9,698 | 32,287 | 22,409 | 41,985 | 333 | dots-3-note-preview, qwen3.8-27b |
| form_04 | 3. Answering | 1 | 12,972 | 13,362 | 7,082 | 26,334 | 114 | qwen3.8-27b |
| form_05 | 1. Reading the scans | 12 | 28,641 | 47,571 | 27,942 | 76,212 | 976 | gemma-4-31b-it, nemotron-3-nano-omni-30b-a3b-reasoning, qwen3.8-27b |
| form_05 | 3. Answering | 3 | 38,252 | 26,329 | 13,453 | 64,581 | 248 | qwen3.8-27b |

## Total per form (both steps)

| form | requests | prompt | completion | of which reasoning | total | model time (s) |
|---|---|---|---|---|---|---|
| form_01 | 3 | 13,352 | 18,082 | 10,601 | 31,434 | 387 |
| form_02 | 6 | 30,358 | 44,877 | 33,850 | 75,235 | 846 |
| form_03 | 13 | 49,075 | 65,134 | 43,332 | 114,209 | 957 |
| form_04 | 5 | 22,670 | 45,649 | 29,491 | 68,319 | 448 |
| form_05 | 15 | 66,893 | 73,900 | 41,395 | 140,793 | 1224 |
| **all forms** | 42 | 182,348 | 247,642 | 158,669 | 429,990 | 3862 |

## Per model

| step | model | requests | prompt | completion | of which reasoning |
|---|---|---|---|---|---|
| 1. Reading the scans | dots-3-note-preview | 3 | 5,154 | 31,018 | 25,703 |
| 1. Reading the scans | gemma-4-31b-it | 1 | 738 | 1,723 | 0 |
| 1. Reading the scans | nemotron-3-nano-omni-30b-a3b-reasoning | 7 | 18,251 | 42,036 | 34,813 |
| 1. Reading the scans | qwen3.8-27b | 22 | 57,268 | 85,326 | 46,518 |
| 3. Answering | qwen3.8-27b | 9 | 100,937 | 87,539 | 51,635 |

## Detail: 1. Reading the scans

| form | request | model | result | prompt | completion | of which reasoning | seconds |
|---|---|---|---|---|---|---|---|
| form_01 | page 01 | qwen3.8-27b | used | 2,660 | 5,594 | 2,337 | 88 |
| form_01 | page 02 | qwen3.8-27b | used | 2,660 | 2,605 | 1,874 | 43 |
| form_02 | page 01 | qwen3.8-27b | used | 2,660 | 3,763 | 1,616 | 56 |
| form_02 | page 02 | qwen3.8-27b | used | 2,660 | 7,229 | 5,168 | 102 |
| form_02 | page 03 | qwen3.8-27b | used | 2,660 | 2,666 | 1,581 | 47 |
| form_02 | page 04 | nemotron-3-nano-omni-30b-a3b-reasoning | used | 2,616 | 7,573 | 5,200 | 170 |
| form_03 | page 01 | nemotron-3-nano-omni-30b-a3b-reasoning | used | 2,616 | 1,449 | 1,455 | 36 |
| form_03 | page 02 | nemotron-3-nano-omni-30b-a3b-reasoning | used | 2,616 | 12,625 | 9,404 | 238 |
| form_03 | page 03 | qwen3.8-27b | used | 2,660 | 944 | 729 | 62 |
| form_03 | page 03 | nemotron-3-nano-omni-30b-a3b-reasoning | failed (unparseable), page re-requested | 2,616 | 3,446 | 3,747 | 54 |
| form_03 | page 04 | dots-3-note-preview | used | 1,718 | 15,480 | 11,304 | 152 |
| form_03 | page 05 | qwen3.8-27b | used | 2,660 | 5,031 | 1,974 | 30 |
| form_03 | page 06 | nemotron-3-nano-omni-30b-a3b-reasoning | used | 2,616 | 5,592 | 5,338 | 115 |
| form_03 | page 07 | dots-3-note-preview | used | 1,718 | 2,738 | 2,386 | 29 |
| form_03 | page 08 | qwen3.8-27b | used | 2,660 | 1,530 | 1,324 | 11 |
| form_03 | page 09 | qwen3.8-27b | used | 2,660 | 1,491 | 742 | 38 |
| form_03 | page 09 | nemotron-3-nano-omni-30b-a3b-reasoning | failed (unparseable), page re-requested | 2,616 | 489 | 504 | 15 |
| form_04 | page 01 | qwen3.8-27b | used | 2,660 | 4,799 | 2,588 | 46 |
| form_04 | page 02 | dots-3-note-preview | used | 1,718 | 12,800 | 12,013 | 130 |
| form_04 | page 03 | qwen3.8-27b | used | 2,660 | 4,761 | 3,489 | 43 |
| form_04 | page 04 | qwen3.8-27b | used | 2,660 | 9,927 | 4,319 | 114 |
| form_05 | page 01 | nemotron-3-nano-omni-30b-a3b-reasoning | used | 2,555 | 10,862 | 9,165 | 310 |
| form_05 | page 02 | qwen3.8-27b | used | 2,599 | 4,823 | 2,487 | 85 |
| form_05 | page 03 | qwen3.8-27b | used | 2,599 | 3,067 | 620 | 56 |
| form_05 | page 03 | qwen3.8-27b | failed (unparseable), page re-requested | 1,955 | 2,296 | 2,296 | 39 |
| form_05 | page 04 | qwen3.8-27b | used | 2,599 | 4,200 | 1,584 | 127 |
| form_05 | page 05 | qwen3.8-27b | used | 2,599 | 5,633 | 1,421 | 64 |
| form_05 | page 06 | qwen3.8-27b | used | 2,599 | 419 | 334 | 6 |
| form_05 | page 07 | qwen3.8-27b | used | 2,599 | 464 | 405 | 11 |
| form_05 | page 08 | qwen3.8-27b | used | 2,599 | 4,033 | 3,109 | 69 |
| form_05 | page 09 | gemma-4-31b-it | used | 738 | 1,723 | 0 | 53 |
| form_05 | page 10 | qwen3.8-27b | used | 2,600 | 2,275 | 1,515 | 21 |
| form_05 | page 11 | qwen3.8-27b | used | 2,600 | 7,776 | 5,006 | 136 |

## Detail: 3. Answering

| form | request | model | result | prompt | completion | of which reasoning | seconds |
|---|---|---|---|---|---|---|---|
| form_01 | S1 try 1 | qwen3.8-27b | used | 8,032 | 9,883 | 6,390 | 257 |
| form_02 | S1 try 1 | qwen3.8-27b | empty answer (provider error), re-requested | 9,094 | 15,357 | 15,357 | 333 |
| form_02 | S1 try 2 | qwen3.8-27b | used | 10,668 | 8,289 | 4,928 | 138 |
| form_03 | S1 try 1 | qwen3.8-27b | used | 9,844 | 4,672 | 2,477 | 75 |
| form_03 | S2 try 1 | qwen3.8-27b | used | 12,075 | 9,647 | 1,948 | 103 |
| form_04 | S1 try 1 | qwen3.8-27b | used | 12,972 | 13,362 | 7,082 | 114 |
| form_05 | S1 try 1 | qwen3.8-27b | used | 13,634 | 11,174 | 5,443 | 108 |
| form_05 | S2_rest try 1 | qwen3.8-27b | used | 11,849 | 7,506 | 3,408 | 72 |
| form_05 | S2 try 1 | qwen3.8-27b | cut off: 18 complete answers kept, rest re-requested | 12,769 | 7,649 | 4,602 | 68 |

Notes:
- Reported by the provider: for nemotron, the reasoning count is sometimes slightly above the completion count.
  The values are copied as returned.
- Answering prompts carry the company's documents (about 8k to 14k tokens). Extraction prompts are one page
  image plus the instructions (about 0.7k to 2.7k tokens, depending on the model's image encoding).
