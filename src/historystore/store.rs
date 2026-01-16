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

#[derive(Debug, Clone, Copy, Default)]
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

        let (index, last_base) = {
            let state = self.state.get_or_insert_default();

            if state.count >= self.shard_size {
                state.last_base += self.shard_size;
                state.count = 0;
            }

            (state.last_base + state.count, state.last_base)
        };

        let shard_path = self.shard_path(last_base);

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

        if let Some(state) = self.state.as_mut() {
            state.count += 1;
        }

        Ok(index)
    }

    /// Returns a lazy iterator that yields records in disk order (by global ID).
    pub fn stream_many<'a>(&'a self, indices: &[usize]) -> HistoryStream<'a> {
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
        sorted_reqs.dedup();

        HistoryStream {
            store: self,
            sorted_reqs: sorted_reqs.into_iter(),
            current_reader: None,
            current_shard_base: None,
            current_line_in_shard: 0,
        }
    }

    pub fn read_many(&self, indices: &[usize]) -> Result<Vec<HistoryRecord>, AicoError> {
        if indices.is_empty() {
            return Ok(Vec::new());
        }

        let mut records_map = HashMap::with_capacity(indices.len());
        for result in self.stream_many(indices) {
            let (id, record) = result?;
            records_map.insert(id, record);
        }

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

pub struct HistoryStream<'a> {
    store: &'a HistoryStore,
    sorted_reqs: std::vec::IntoIter<(usize, usize, usize)>,
    current_reader: Option<BufReader<fs::File>>,
    current_shard_base: Option<usize>,
    current_line_in_shard: usize,
}

impl<'a> Iterator for HistoryStream<'a> {
    type Item = Result<(usize, HistoryRecord), AicoError>;

    fn next(&mut self) -> Option<Self::Item> {
        let (shard_base, target_offset, global_id) = self.sorted_reqs.next()?;

        // 1. Ensure correct shard file is open
        if self.current_shard_base != Some(shard_base) {
            let path = self.store.shard_path(shard_base);
            if !path.exists() {
                return Some(Err(AicoError::Session(format!(
                    "Shard missing: {:?}",
                    path
                ))));
            }
            match fs::File::open(&path) {
                Ok(f) => {
                    self.current_reader = Some(BufReader::with_capacity(64 * 1024, f));
                    self.current_shard_base = Some(shard_base);
                    self.current_line_in_shard = 0;
                }
                Err(e) => return Some(Err(AicoError::Io(e))),
            }
        }

        let reader = self.current_reader.as_mut()?;

        // 2. Seek to target line
        while self.current_line_in_shard < target_offset {
            match reader.skip_until(b'\n') {
                Ok(0) => {
                    return Some(Err(AicoError::Session(format!(
                        "Record ID {} not found",
                        global_id
                    ))));
                }
                Ok(_) => self.current_line_in_shard += 1,
                Err(e) => return Some(Err(AicoError::Io(e))),
            }
        }

        // 3. Read and Deserialize
        let mut buffer = Vec::new();
        match reader.read_until(b'\n', &mut buffer) {
            Ok(0) => Some(Err(AicoError::Session(format!(
                "Record ID {} not found",
                global_id
            )))),
            Ok(_) => {
                self.current_line_in_shard += 1;
                // Resilience: Handle deserialization failure gracefully
                match serde_json::from_slice::<HistoryRecord>(&buffer) {
                    Ok(record) => Some(Ok((global_id, record))),
                    Err(e) => {
                        eprintln!(
                            "[WARN] Failed to parse history record ID {}: {}. Skipping.",
                            global_id, e
                        );
                        // Recursively try next item
                        self.next()
                    }
                }
            }
            Err(e) => Some(Err(AicoError::Io(e))),
        }
    }
}
