### Fixed — EML → PDF decodes mail text in the character sets mail uses

EML → PDF decodes text parts and encoded header words in the character set
the mail names if it is one of the character sets mail is written in:
UTF-8/16/32, ASCII, ISO-8859-x, Windows-125x, KOI8, Mac Roman, the Japanese,
Chinese and Korean mail sets, and the labels mail clients use for them
(e.g. `ISO8859-1`, `iso-8859-8-i`, `ks_c_5601-1987`). Labels that mail
clients and browsers read as a superset get the superset (ISO-8859-1 as
Windows-1252, Shift_JIS as CP932, EUC-KR as CP949, GB2312 as GBK, Big5 as
CP950). Any other label is read as UTF-8, with bytes that aren't valid UTF-8
replaced; a mail naming a character set Python doesn't know used to fail
with a `500`. Header text sent as raw 8-bit bytes is read as UTF-8, a
folded header line keeps its space, and a damaged encoded word is shown as
it is. The body is the first HTML part of the mail's own text (attachments
and attached mails don't count), else the first plain-text part.
