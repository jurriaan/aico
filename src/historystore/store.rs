use crate::exceptions::AicoError;
use crate::models::HistoryRecord;
use std::collections::HashMap;
use std::fs::{self, OpenOptions};
use std::io::{BufRead, BufReader, BufWriter, Write};
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

        let file = options.open(&shard_path)?;
        let mut writer = BufWriter::new(file);

        serde_json::to_writer(&mut writer, record)?;
        writeln!(writer)?;
        writer.flush()?;

        state.count += 1;
        self.state = Some(state);

        Ok(index)
    }

    pub fn read_many(&self, indices: &[usize]) -> Result<Vec<HistoryRecord>, AicoError> {
        if indices.is_empty() {
            return Ok(Vec::new());
        }

        // 1. Sort requests by (Shard Base, Offset) to enable sequential scan
        let mut sorted_reqs: Vec<(usize, usize, usize)> = indices
            .iter()
            .map(|&global_id| {
                (
                    (global_id / self.shard_size) * self.shard_size,
                    global_id % self.shard_size,
                    global_id,
                )
            })
            .collect();

        sorted_reqs.sort_unstable();

        let mut records_map: HashMap<usize, HistoryRecord> = HashMap::new();

        // 2. Process by shard using chunks
        for shard_group in sorted_reqs.chunk_by(|a, b| a.0 == b.0) {
            let base = shard_group[0].0;
            let path = self.shard_path(base);
            if !path.exists() {
                return Err(AicoError::Session(format!("Shard missing: {:?}", path)));
            }

            let file = fs::File::open(path)?;
            let mut reader = BufReader::with_capacity(64 * 1024, file);
            let mut buffer = Vec::new();
            let mut current_line = 0;

            for &(_, target_offset, global_id) in shard_group {
                while current_line < target_offset {
                    if reader.skip_until(b'\n')? == 0 {
                        break;
                    }
                    current_line += 1;
                }

                if current_line == target_offset {
                    buffer.clear();
                    if reader.read_until(b'\n', &mut buffer)? > 0 {
                        let record: HistoryRecord = serde_json::from_slice(&buffer)?;
                        records_map.insert(global_id, record);
                        current_line += 1;
                    }
                }
            }
        }

        // 3. Reassemble in order (handles potential duplicate IDs in original indices)
        let mut results = Vec::with_capacity(indices.len());
        for &idx in indices {
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
