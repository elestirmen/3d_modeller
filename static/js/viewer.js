/**
 * Three.js tabanlı model görüntüleyici. Tek bir WebGL bağlamı tutar ve
 * modeller arasında yeniden kullanır.
 */

/* global THREE */

export const SWATCHES = [
  { key: 'accent', label: 'Mor', color: '#5d5af2' },
  { key: 'white', label: 'Beyaz PLA', color: '#ecedf1' },
  { key: 'gray', label: 'Gri', color: '#8b909b' },
  { key: 'black', label: 'Siyah', color: '#2a2c33' },
  { key: 'blue', label: 'Mavi', color: '#3b82f6' },
  { key: 'green', label: 'Yeşil', color: '#10b981' },
  { key: 'orange', label: 'Turuncu', color: '#f59e0b' },
  { key: 'red', label: 'Kırmızı', color: '#ef4444' },
  { key: 'pink', label: 'Pembe', color: '#ec4899' },
  { key: 'wood', label: 'Ahşap', color: '#c6a06a' },
];

const Z_UP_FORMATS = new Set(['stl', '3mf', 'ply']);

export function webglAvailable() {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(window.WebGLRenderingContext && (canvas.getContext('webgl2') || canvas.getContext('webgl')));
  } catch {
    return false;
  }
}

export class ModelViewer {
  constructor(container) {
    this.container = container;
    this.renderer = null;
    this.object = null;
    this.token = 0;
    this.running = false;
    let saved = {};
    try {
      saved = JSON.parse(localStorage.getItem('viewerSettings') || '{}') || {};
    } catch { /* depolama kapalı */ }
    this.settings = { autoRotate: true, wireframe: false, showBox: false, swatch: 'accent', ...saved };
    this.hasOriginalColors = false;
    this.originalMaterials = new Map();
    this.onChange = null;
  }

  saveSettings() {
    try {
      localStorage.setItem('viewerSettings', JSON.stringify({
        autoRotate: this.settings.autoRotate,
        swatch: this.settings.swatch,
        showBox: this.settings.showBox,
      }));
    } catch { /* yoksay */ }
  }

  setContainer(container) {
    if (this.container === container) return;
    this.resizeObserver?.unobserve(this.container);
    this.container = container;
    this.resizeObserver?.observe(container);
    if (this.renderer) container.prepend(this.renderer.domElement);
  }

  init() {
    if (this.renderer) {
      if (!this.renderer.domElement.isConnected) this.container.prepend(this.renderer.domElement);
      return true;
    }
    if (!window.THREE || !webglAvailable()) return false;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'high-performance' });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    renderer.setClearColor(0x000000, 0);
    renderer.outputEncoding = THREE.sRGBEncoding;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.86;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer = renderer;
    this.container.prepend(renderer.domElement);

    this.scene = new THREE.Scene();
    if (THREE.RoomEnvironment) {
      const pmrem = new THREE.PMREMGenerator(renderer);
      this.scene.environment = pmrem.fromScene(new THREE.RoomEnvironment(), 0.04).texture;
      pmrem.dispose();
    }

    this.camera = new THREE.PerspectiveCamera(35, 1, 0.1, 5000);
    this.hemi = new THREE.HemisphereLight(0xffffff, 0x3a3c55, 0.22);
    this.scene.add(this.hemi);
    this.key = new THREE.DirectionalLight(0xffffff, 1.25);
    this.key.castShadow = true;
    this.key.shadow.mapSize.set(2048, 2048);
    this.key.shadow.bias = -0.0004;
    this.key.shadow.normalBias = 0.02;
    this.scene.add(this.key);
    this.scene.add(this.key.target);

    this.ground = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 1),
      new THREE.ShadowMaterial({ color: 0x000000, opacity: 0.2 }),
    );
    this.ground.rotation.x = -Math.PI / 2;
    this.ground.receiveShadow = true;
    this.scene.add(this.ground);

    this.controls = new THREE.OrbitControls(this.camera, renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.autoRotateSpeed = 1.4;
    this.controls.addEventListener('start', () => {
      this.userInteracted = true;
    });

    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.container);
    this.resize();
    this.applyTheme();
    window.addEventListener('themechange', () => this.applyTheme());
    return true;
  }

  applyTheme() {
    if (!this.scene) return;
    const dark = document.documentElement.dataset.theme === 'dark'
      || (!document.documentElement.dataset.theme && window.matchMedia('(prefers-color-scheme: dark)').matches);
    this.ground.material.opacity = dark ? 0.42 : 0.2;
    if (this.grid) {
      this.grid.material.opacity = dark ? 0.22 : 0.3;
      this.grid.material.color.set(dark ? 0x9aa0ff : 0x6d6f8a);
    }
  }

  resize() {
    if (!this.renderer) return;
    const { clientWidth: width, clientHeight: height } = this.container;
    if (!width || !height) return;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
  }

  start() {
    if (this.running || !this.renderer) return;
    this.running = true;
    const loop = () => {
      if (!this.running) return;
      this.controls.autoRotate = this.settings.autoRotate && Boolean(this.object);
      this.controls.update();
      this.renderer.render(this.scene, this.camera);
      this.frame = requestAnimationFrame(loop);
    };
    loop();
  }

  stop() {
    this.running = false;
    cancelAnimationFrame(this.frame);
  }

  clear() {
    this.token += 1;
    if (this.object) {
      this.scene.remove(this.object);
      this.object.traverse((child) => {
        child.geometry?.dispose?.();
        const materials = Array.isArray(child.material) ? child.material : [child.material];
        materials.filter(Boolean).forEach((material) => {
          Object.values(material).forEach((value) => value?.isTexture && value.dispose());
          material.dispose?.();
        });
      });
      this.object = null;
    }
    this.originalMaterials.forEach((material) => {
      (Array.isArray(material) ? material : [material]).forEach((item) => item?.dispose?.());
    });
    this.originalMaterials.clear();
    if (this.boxHelper) {
      this.scene.remove(this.boxHelper);
      this.boxHelper = null;
    }
    if (this.grid) {
      this.scene.remove(this.grid);
      this.grid.geometry.dispose();
      this.grid.material.dispose();
      this.grid = null;
    }
    this.dims = null;
  }

  loaderFor(format) {
    switch (format) {
      case 'stl': return THREE.STLLoader && new THREE.STLLoader();
      case '3mf': return THREE.ThreeMFLoader && new THREE.ThreeMFLoader();
      case 'obj': return THREE.OBJLoader && new THREE.OBJLoader();
      case 'ply': return THREE.PLYLoader && new THREE.PLYLoader();
      case 'glb':
      case 'gltf': return THREE.GLTFLoader && new THREE.GLTFLoader();
      default: return null;
    }
  }

  parseCompact(buffer) {
    const view = new DataView(buffer);
    const magic = String.fromCharCode(view.getUint8(0), view.getUint8(1), view.getUint8(2), view.getUint8(3));
    if (magic !== 'M3DB' || view.getUint32(4, true) !== 1) throw new Error('Geçersiz mesh verisi');
    const vertexCount = view.getUint32(8, true);
    const indexCount = view.getUint32(12, true);
    const positions = new Float32Array(buffer, 16, vertexCount * 3);
    const indices = new Uint32Array(buffer, 16 + vertexCount * 12, indexCount);
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setIndex(new THREE.BufferAttribute(indices, 1));
    geometry.computeVertexNormals();
    return geometry;
  }

  loadCompact(url, format, token, onProgress) {
    return new Promise((resolve, reject) => {
      const loader = new THREE.FileLoader();
      loader.setResponseType('arraybuffer');
      loader.load(url, (buffer) => {
        if (token !== this.token) return;
        try {
          this.present(this.buildObject(this.parseCompact(buffer), format), format);
          resolve(this.dims);
        } catch (error) {
          reject(error);
        }
      }, (event) => {
        if (token === this.token && onProgress) onProgress(event.lengthComputable && event.total ? event.loaded / event.total : null);
      }, reject);
    });
  }

  /**
   * Modeli yükle. onProgress(0..1 | null) ilerleme bildirir.
   * Başka bir yükleme başlatılırsa eski sonuç yok sayılır.
   */
  load(url, format, { onProgress, meshUrl } = {}) {
    if (!this.init()) return Promise.reject(new Error('Tarayıcınız WebGL desteklemiyor'));
    this.clear();
    const token = this.token;
    const loader = this.loaderFor(format);
    if (!loader && !meshUrl) return Promise.reject(new Error(`${format.toUpperCase()} önizlemesi desteklenmiyor`));
    this.start();
    this.flat = !['glb', 'gltf', 'obj'].includes(format);
    if (meshUrl) {
      return this.loadCompact(meshUrl, format, token, onProgress).catch((error) => {
        if (token !== this.token) throw error;
        console.warn('Kompakt mesh açılamadı, dosya doğrudan yükleniyor', error);
        if (!loader) throw error;
        return this.load(url, format, { onProgress });
      });
    }

    return new Promise((resolve, reject) => {
      loader.load(
        url,
        (result) => {
          if (token !== this.token) return;
          try {
            const object = this.buildObject(result, format);
            this.present(object, format);
            resolve(this.dims);
          } catch (error) {
            reject(error);
          }
        },
        (event) => {
          if (token !== this.token || !onProgress) return;
          onProgress(event.lengthComputable && event.total ? event.loaded / event.total : null);
        },
        (error) => {
          if (token !== this.token) return;
          reject(error instanceof Error ? error : new Error('Model yüklenemedi'));
        },
      );
    });
  }

  makeMaterial() {
    const swatch = SWATCHES.find((item) => item.key === this.settings.swatch) || SWATCHES[0];
    return new THREE.MeshStandardMaterial({
      color: new THREE.Color(swatch.color).convertSRGBToLinear(),
      roughness: 0.52,
      metalness: 0.0,
      envMapIntensity: 0.5,
      wireframe: this.settings.wireframe,
      side: THREE.DoubleSide,
      flatShading: this.flat !== false,
    });
  }

  buildObject(result, format) {
    this.hasOriginalColors = false;
    let object;
    if (result && result.isBufferGeometry) {
      const geometry = result;
      if (!geometry.attributes.normal) geometry.computeVertexNormals();
      const hasColors = Boolean(geometry.attributes.color);
      object = new THREE.Mesh(geometry, this.makeMaterial());
      if (hasColors) {
        this.hasOriginalColors = true;
        this.originalMaterials.set(object.uuid, new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.5, metalness: 0.02 }));
      }
    } else {
      object = result.scene || result;
      object.traverse((child) => {
        if (!child.isMesh) return;
        if (child.geometry && !child.geometry.attributes.normal) child.geometry.computeVertexNormals();
        const original = child.material;
        const materials = Array.isArray(original) ? original : [original];
        const colorful = materials.some((material) => material && (material.vertexColors || material.map
          || (material.color && material.color.getHex() !== 0xffffff)));
        if (colorful && (format === '3mf' || format === 'glb' || format === 'gltf')) {
          this.hasOriginalColors = true;
        }
        this.originalMaterials.set(child.uuid, original);
        child.material = this.makeMaterial();
      });
    }

    const holder = new THREE.Group();
    holder.add(object);
    if (Z_UP_FORMATS.has(format)) object.rotation.x = -Math.PI / 2;
    return holder;
  }

  present(holder, format) {
    const inner = holder.children[0];
    inner.updateMatrixWorld(true);

    // Gerçek (dosya) eksenlerindeki ölçüler: baskı formatlarında X × Y × Z.
    const rawBox = new THREE.Box3().setFromObject(holder);
    const size = rawBox.getSize(new THREE.Vector3());
    this.dims = Z_UP_FORMATS.has(format) ? [size.x, size.z, size.y] : [size.x, size.y, size.z];

    const center = rawBox.getCenter(new THREE.Vector3());
    inner.position.x -= center.x;
    inner.position.z -= center.z;
    inner.position.y -= rawBox.min.y;
    holder.updateMatrixWorld(true);

    let triangles = 0;
    holder.traverse((child) => {
      if (!child.isMesh) return;
      const count = child.geometry.index ? child.geometry.index.count / 3 : (child.geometry.attributes.position?.count || 0) / 3;
      triangles += count;
    });
    const castShadow = triangles < 1_500_000;
    holder.traverse((child) => {
      if (child.isMesh) {
        child.castShadow = castShadow;
        child.receiveShadow = false;
      }
    });

    this.object = holder;
    this.scene.add(holder);
    this.applyMaterial();

    const radius = Math.max(size.length() / 2, 1);
    this.radius = radius;
    this.height = size.y;
    const groundSize = radius * 12;
    this.ground.scale.set(groundSize, groundSize, 1);

    const gridStep = [1, 2, 5, 10, 20, 50, 100].find((step) => radius / step < 12) || 100;
    const divisions = Math.ceil((radius * 3) / gridStep) * 2;
    this.grid = new THREE.GridHelper(divisions * gridStep, divisions, 0x6d6f8a, 0x6d6f8a);
    this.grid.material.transparent = true;
    this.grid.material.depthWrite = false;
    this.grid.position.y = 0.001;
    this.scene.add(this.grid);
    this.applyTheme();

    this.key.position.set(radius * 1.6, radius * 3.2, radius * 2.2);
    this.key.target.position.set(0, size.y / 3, 0);
    const shadowCam = this.key.shadow.camera;
    shadowCam.left = -radius * 2;
    shadowCam.right = radius * 2;
    shadowCam.top = radius * 2;
    shadowCam.bottom = -radius * 2;
    shadowCam.near = radius * 0.1;
    shadowCam.far = radius * 12;
    shadowCam.updateProjectionMatrix();

    this.camera.near = Math.max(radius / 200, 0.01);
    this.camera.far = radius * 200;
    this.camera.updateProjectionMatrix();
    this.controls.minDistance = radius * 0.2;
    this.controls.maxDistance = radius * 20;
    this.resetView();
    this.updateBox();
  }

  resetView() {
    if (!this.object) return;
    const radius = this.radius || 50;
    const fov = (this.camera.fov * Math.PI) / 180;
    const distance = (radius / Math.sin(fov / 2)) * 1.3;
    const target = new THREE.Vector3(0, (this.height || radius) * 0.45, 0);
    const direction = new THREE.Vector3(0.9, 0.62, 1.15).normalize();
    this.camera.position.copy(target).addScaledVector(direction, distance);
    this.controls.target.copy(target);
    this.controls.update();
    this.userInteracted = false;
  }

  applyMaterial() {
    if (!this.object) return;
    const useOriginal = this.settings.swatch === 'original' && this.hasOriginalColors;
    this.object.traverse((child) => {
      if (!child.isMesh) return;
      const current = child.material;
      const isOriginal = this.originalMaterials.get(child.uuid) === current;
      if (!isOriginal && current) current.dispose?.();
      if (useOriginal) {
        child.material = this.originalMaterials.get(child.uuid) || this.makeMaterial();
      } else {
        child.material = this.makeMaterial();
      }
      const materials = Array.isArray(child.material) ? child.material : [child.material];
      materials.forEach((material) => {
        if (material) material.wireframe = this.settings.wireframe;
      });
    });
  }

  updateBox() {
    if (this.boxHelper) {
      this.scene.remove(this.boxHelper);
      this.boxHelper = null;
    }
    if (this.settings.showBox && this.object) {
      this.boxHelper = new THREE.BoxHelper(this.object, 0x8b8aff);
      this.scene.add(this.boxHelper);
    }
  }

  set(option, value) {
    this.settings[option] = value;
    if (option === 'swatch' || option === 'wireframe') this.applyMaterial();
    if (option === 'showBox') this.updateBox();
    this.saveSettings();
    this.onChange?.(this.settings);
  }

  snapshot() {
    if (!this.renderer) return null;
    this.renderer.render(this.scene, this.camera);
    return this.renderer.domElement.toDataURL('image/png');
  }

  detach() {
    this.stop();
    this.clear();
    this.renderer?.domElement.remove();
  }
}
