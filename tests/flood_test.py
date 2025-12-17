# flood_test.py
import time

print("Starting flood test...")

# Generate 5,000 lines of text
lines = [f"Line {i}: Checking UI responsiveness..." for i in range(5000)]
large_text = "\n".join(lines)

# Print them all at once
# Before the fix: This would freeze the UI for several seconds
# After the fix: The UI should remain clickable while text appears in chunks
print(large_text)

print("Flood complete.")
