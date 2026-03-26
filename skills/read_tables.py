import os

def read_tables(filename: str, start_line: int, end_line: int) -> str:
    """
    Extract specific lines from a Treasury Bulletin document to parse complex financial tables.
    Use this after `search_officeqa` gives you the correct line numbers.
    
    Args:
        filename: The exact file name (e.g., 'treasury_bulletin_1947_08.txt').
        start_line: The line number to begin reading (1-indexed).
        end_line: The line number to end reading (inclusive).
    
    Returns:
        The exact text of the requested lines.
    """
    base_dir = "data/officeqa/transformed"
    filepath = os.path.join(base_dir, filename)
    
    if not os.path.exists(filepath):
        return f"Error: File '{filename}' not found."
        
    if start_line > end_line or start_line < 1:
        return "Error: Invalid line range specified."
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        if start_line > len(lines):
            return f"Error: File only has {len(lines)} lines."
            
        snippet = lines[start_line-1 : end_line]
        return "".join(snippet)
    except Exception as e:
        return f"Error reading file: {str(e)}"
