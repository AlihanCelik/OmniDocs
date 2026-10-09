OmniDocs 🧠📄
OmniDocs, şirketlerin ve bireylerin kendi özel belgeleri (PDF vb.) üzerinde soru-cevap yapabilmesini sağlayan, %100 yerel ve gizlilik odaklı akıllı bir doküman asistanıdır.

Verileriniz hiçbir zaman dışarıdaki sunuculara veya bulut sağlayıcılarına gönderilmez; tüm okuma, indeksleme, arama ve yanıt üretme süreçleri tamamen kendi cihazınız üzerinde gerçekleşir.

🌟 Ne İşe Yarar?
Belgelerinizi Konuşturur: Yüklediğiniz PDF'leri okur, analiz eder ve sorduğunuz sorulara doğrudan bu belgelerdeki bilgileri kullanarak yanıt verir.

Kaynak ve Sayfa Numarası Gösterir: Uydurma yanıtlar vermez. Her bilginin sonuna alıntının hangi dokümandan ve hangi sayfadan yapıldığını ([Kaynak: dosya.pdf, Sayfa: 3]) ekler.

Kurumsal İzolasyon (Çoklu Kiracı): Farklı şirketlerin veya ekiplerin verilerini birbirinden tamamen ayrı tutar; kullanıcılar yalnızca yetkili oldukları doküman havuzunda arama yapabilir.

Kesintisiz Deneyim: Büyük ve çok sayfalı belgeler yüklenirken sistem kilitlenmez; işleme süreci arka planda devam ederken arayüz ve arama motoru anında yanıt vermeyi sürdürür.

🛠️ Nasıl Çalışır?
Yükleme: Belgenizi yüklersiniz; metinler taranarak anlam bütünlüğünü koruyan parçalara ayrılır.

Akıllı Arama: Sorunuz sisteme ulaştığında, binlerce sayfa taranarak konuyla doğrudan ilgili bölümler saniyeler içinde tespit edilir.

Yeniden Sıralama (Hassas Filtreleme): Bulunan aday sayfalar derinlemesine incelenir ve soruya en net cevabı veren 2-3 kilit paragraf seçilir.

Yerel Yanıt Üretimi: Bilgisayarınızda çalışan yerel dil modeli (Llama 3.2), bu paragrafları okuyup sayfa referanslarıyla birlikte anlaşılır bir yanıt üretir.

🚀 Hızlı Başlangıç
Sistemi bilgisayarınızda çalıştırmak için gereken temel komutlar:

Bash
# 1. Gerekli kütüphaneleri yükleyin
pip install -r requirements.txt

# 2. Arka plan işlemcisini başlatın (Terminal 1)
celery -A tasks.celery_app worker --loglevel=info --pool=solo

# 3. API sunucusunu başlatın (Terminal 2)
uvicorn main:app --reload --port 8000
Sunucu açıldıktan sonra tarayıcınızdan http://localhost:8000/docs adresine giderek arayüz üzerinden hemen belge yükleyebilir ve sorularınızı sormaya başlayabilirsiniz.

🔒 Gizlilik Güvencesi
OmniDocs; FastAPI, Qdrant ve Ollama gibi tamamen yerel çalışabilen açık teknolojiler üzerine kurulmuştur. Cihazınızı uçak moduna alsanız dahi çalışmaya devam eder; ticari sırlar, sözleşmeler ve şirket içi veriler asla bilgisayarınızın dışına sızmaz.