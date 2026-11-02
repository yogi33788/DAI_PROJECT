import numpy as np
import pandas as pd

# 120-balls max resource targets for 0 to 9 wickets lost at the start of the innings (b = 120)
targets_at_120 = [100.0, 93.4, 85.1, 74.9, 62.7, 49.0, 34.9, 22.0, 11.9, 4.7]
# Decay constants tuned for 120 balls T20 format
L = [0.015, 0.016, 0.017, 0.018, 0.020, 0.022, 0.025, 0.030, 0.040, 0.060]

balls = np.arange(1, 121)
data = {}

for w in range(10):
    # Normalize so that at b = 120, the value equals exactly targets_at_120[w]
    denom = 1 - np.exp(-L[w] * 120)
    data[f'w{w}'] = [
        round(targets_at_120[w] * (1 - np.exp(-L[w] * b)) / denom, 2)
        for b in balls
    ]

df = pd.DataFrame(data)
df.insert(0, 'balls_remaining', balls)

# Save to CSV
output_filename = 'dls_resource_table_120x10.csv'
df.to_csv(output_filename, index=False)
print(f"Successfully generated and saved: {output_filename}")
print(f"Check at 120 balls remaining, w0: {df.loc[df['balls_remaining'] == 120, 'w0'].values[0]}%")
