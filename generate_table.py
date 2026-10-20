import numpy as np
import pandas as pd

# Standard D/L exponential model parameters for resources
# Wickets 0 through 9
R0 = [100.0, 93.4, 85.1, 74.9, 62.7, 49.0, 34.9, 22.0, 11.9, 4.7]
L  = [0.0090, 0.0092, 0.0096, 0.0102, 0.0112, 0.0128, 0.0152, 0.0190, 0.0260, 0.0450]

data = {}

for w in range(10):
    # Calculate resource percentage remaining for each ball (1 to 120)
    data[f'w{w}'] = [
        round(R0[w] * (1 - np.exp(-L[w] * b)), 2)
        for b in range(1, 121)
    ]

df = pd.DataFrame(data)
df.insert(0, 'balls_remaining', range(1, 121))

# Save to CSV
df.to_csv('dls_resource_table_120x10.csv', index=False)
