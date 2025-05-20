def sanitize_text(text):
	"""
	Sanitize the input text by removing any unwanted characters or formatting.
	
	Args:
		text (str): The input text to be sanitized.
	
	Returns:
		str: The sanitized text.
	"""
	# Remove any unwanted characters or formatting
	if isinstance(text, str):
		return text.replace('\n', ' ').replace('\r', '').strip()

	return text