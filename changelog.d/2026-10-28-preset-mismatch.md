### Fixed — a pre-set converter no longer picks another target for a file that doesn't fit

On a conversion page such as "JPG to PDF", the target list is hidden. Until
now, a file that can't become the page's target (a PDF dropped on "JPG to
PDF", say) was converted to the first target it could reach (for a PDF:
TXT) without a word. Now:

- the target list appears, starting at "— choose a target format —";
- a note says which file the page expects;
- nothing converts until a target is chosen.

In a batch, each file that doesn't fit gets the same choice in its own row.
The same applies on "Video to GIF".
