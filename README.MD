
## PRJ: India’s state budgets with LLMs

Collection of state budget original PDFs, along with output of the LLM
runs, and prompts.

The goal is to convert these PDFs into accurate transcriptions into a text
format (currently CSV) and to translate from Indic characters to English.


## Layout of repository

* DATA: Location of all the source pdf files that are the state budgets
* OUT: Location of the parsed CSVs. The output tree here corresponds exactly to
  the tree in DATA directory, and the naming is consistent
* PROMPTS: Language model prompts
* SRC: Source code, in particular extraction_pipeline.py

