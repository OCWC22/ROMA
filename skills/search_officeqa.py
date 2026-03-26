import os
import glob
from typing import List

def search_officeqa(query: str, year_filter: str = "") -> List[str]:
    """
    Search across historical U.S. Treasury Bulletin documents for specific terms.
    
    Args:
        query: The string phrase to find (e.g. "Public Works Administration").
        year_filter: Optional year to constrain the search (e.g., "1947").
    
    Returns:
        List of strings containing the file paths and matching snippets.
    """
    base_dir = "data/officeqa/transformed"
    if not os.path.exists(base_dir):
        return ["Error: Corpus directory not found. Are we inside the container?"]
        
    pattern = f"*{year_filter}*.txt" if year_filter else "*.txt"
    files = glob.glob(os.path.join(base_dir, pattern))
    
    results = []
    for fpath in files:
        matches = []
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if query.lower() in line.lower():
                        matches.append(f"Line {i+1}: {line.strip()}")
            
            if matches:
                res_str = f"Found {len(matches)} matches in {os.path.basename(fpath)}:\n"
                res_str += "\n".join(matches[:10]) # Limit to top 10 to avoid blasting context
                results.append(res_str)
        except Exception as e:
            continue
            
    if not results:
        return [f"No results found for '{query}' in year '{year_filter}'"]
        
    return results[:5] # Limit total files to prevent context exhaustion
