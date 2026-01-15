use crate::exceptions::AicoError;
use crate::models::HistoryRecord;
use std::collections::{HashMap, HashSet};
use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;

pub const SHARD_SIZE: usize = 10_000;

#[derive(Debug)]
pub struct HistoryStore {
    root: PathBuf,
    shard_size: usize,
    state: Option<StoreState>,
}

#[derive(Debug, Clone, Copy)]
struct StoreState {
    last_base: usize,
    count: usize,
}

impl HistoryStore {
    pub fn new(root: PathBuf) -> Self {
        Self {
            root,
            shard_size: SHARD_SIZE,
            state: None,
        }
    }

    /// For testing, allow overriding shard size
    pub fn new_with_shard_size(root: PathBuf, shard_size: usize) -> Self {
        Self {
            root,
            shard_size,
            state: None,
        }
    }

    /// Appends a record and returns its global index.
    pub fn append(&mut self, record: &HistoryRecord) -> Result<usize, AicoError> {
        if self.state.is_none() {
            self.refresh_state()?;
        }

        let mut state = self.state.unwrap_or(StoreState {
            last_base: 0,
            count: 0,
        });

        if state.count >= self.shard_size {
            state.last_base += self.shard_size;
            state.count = 0;
        }

        let index = state.last_base + state.count;
        let shard_path = self.shard_path(state.last_base);

        if let Some(parent) = shard_path.parent() {
            fs::create_dir_all(parent)?;
        }

        let mut options = OpenOptions::new();
        options.create(true).append(true);

        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }

        let mut file = options.open(&shard_path)?;

        serde_json::to_writer(&mut file, record)?;
        writeln!(file)?;

        state.count += 1;
        self.state = Some(state);

        Ok(index)
    }

    pub fn read_many(&self, indices: &[usize]) -> Result<Vec<HistoryRecord>, AicoError> {
        if indices.is_empty() {
            return Ok(Vec::new());
        }

        // Group by shard
        let mut by_shard: HashMap<usize, HashSet<usize>> = HashMap::new();
        for &idx in indices {
            let base = (idx / self.shard_size) * self.shard_size;
            let offset = idx % self.shard_size;
            by_shard.entry(base).or_default().insert(offset);
        }

        let mut records_map: HashMap<usize, HistoryRecord> = HashMap::new();

        for (base, offsets) in by_shard {
            let path = self.shard_path(base);
            if !path.exists() {
                return Err(AicoError::Session(format!("Shard missing: {:?}", path)));
            }

            let file = fs::File::open(path)?;
            let mut reader = BufReader::with_capacity(64 * 1024, file);
            let mut buffer = Vec::new();

            let max_needed = *offsets.iter().max().unwrap_or(&0);
            let mut current_line = 0;

            loop {
                if offsets.contains(&current_line) {
                    buffer.clear();
                    let bytes_read = reader.read_until(b'\n', &mut buffer)?;
                    if bytes_read == 0 {
                        break;
                    }
                    let record: HistoryRecord = serde_json::from_slice(&buffer)?;
                    records_map.insert(base + current_line, record);
                } else if reader.skip_until(b'\n')? == 0 {
                    break;
                }

                if current_line >= max_needed {
                    break;
                }
                current_line += 1;
            }
        }

        // Reassemble in order
        let mut results = Vec::new();
        for &idx in indices {
            // Use .get() instead of .remove() to allow duplicate IDs in the same request
            if let Some(rec) = records_map.get(&idx) {
                results.push(rec.clone());
            } else {
                return Err(AicoError::Session(format!("Record ID {} not found", idx)));
            }
        }

        Ok(results)
    }

    // --- Helpers ---

    fn shard_path(&self, base: usize) -> PathBuf {
        self.root.join(format!("{}.jsonl", base))
    }

    fn refresh_state(&mut self) -> Result<(), AicoError> {
        if !self.root.exists() {
            self.state = Some(StoreState {
                last_base: 0,
                count: 0,
            });
            return Ok(());
        }

        let mut max_base = None;

        for entry in fs::read_dir(&self.root)? {
            let entry = entry?;
            let path = entry.path();
            if path.extension().and_then(|s| s.to_str()) == Some("jsonl")
                && let Some(stem) = path.file_stem().and_then(|s| s.to_str())
                && let Ok(base) = stem.parse::<usize>()
                && max_base.is_none_or(|m| base > m)
            {
                max_base = Some(base);
            }
        }

        let base = max_base.unwrap_or(0);
        let path = self.shard_path(base);

        let count = if path.exists() {
            let file = fs::File::open(&path)?;
            let mut reader = BufReader::with_capacity(64 * 1024, file);
            let mut c = 0;
            while reader.skip_until(b'\n')? > 0 {
                c += 1;
            }
            c
        } else {
            0
        };

        self.state = Some(StoreState {
            last_base: base,
            count,
        });
        Ok(())
    }
}
